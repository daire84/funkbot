import discord
from discord.ext import commands, tasks
import asyncio
import os
import random
import mysql.connector
from datetime import datetime, timedelta
import logging
import json
import aiohttp
from typing import Optional

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Bot configuration with slash commands
intents = discord.Intents.default()
intents.voice_states = True
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Enhanced join messages with emojis
JOIN_MESSAGES = [
    "🎉 **{user}** is now hanging out in **{channel}**!",
    "🚀 **{user}** has joined **{channel}**!",
    "😎 **{user}** is chilling in **{channel}**!",
    "⚡ **{user}** jumped into **{channel}**!",
    "🎮 **{user}** entered **{channel}**!",
    "🎵 **{user}** is vibing in **{channel}**!",
    "✨ **{user}** is now in **{channel}**!",
    "🎪 **{user}** decided to hang in **{channel}**!",
    "🌟 **{user}** popped into **{channel}**!",
    "🎊 **{user}** is socializing in **{channel}**!"
]

LEAVE_MESSAGES = [
    "👋 **{user}** left **{channel}** after **{duration}**",
    "🚪 **{user}** bounced from **{channel}** (**{duration}**)",
    "✌️ **{user}** said goodbye to **{channel}** (**{duration}**)",
    "🏃‍♂️ **{user}** dipped from **{channel}** (**{duration}**)"
]

# Achievement system
ACHIEVEMENTS = {
    "first_join_today": {"name": "Early Bird", "emoji": "🐦", "description": "First to join voice today!"},
    "social_butterfly": {"name": "Social Butterfly", "emoji": "🦋", "description": "Joined 5 different channels in one day!"},
    "marathon_chatter": {"name": "Marathon Chatter", "emoji": "🏃‍♂️", "description": "Spent 4+ hours in voice today!"},
    "night_owl": {"name": "Night Owl", "emoji": "🦉", "description": "Joined voice after midnight!"},
    "popular_host": {"name": "Popular Host", "emoji": "🎪", "description": "Had 5+ people join your channel!"},
    "loyal_friend": {"name": "Loyal Friend", "emoji": "💎", "description": "100 total voice joins!"},
    "speed_demon": {"name": "Speed Demon", "emoji": "⚡", "description": "Joined and left within 30 seconds!"}
}

# Database configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'mariadb'),
    'database': os.getenv('DB_NAME', 'funkbot_db'),
    'user': os.getenv('DB_USER', 'funkbot_user'),
    'password': os.getenv('DB_PASSWORD'),
    'charset': 'utf8mb4'
}

def get_db_connection():
    """Get database connection with retry logic"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        return connection
    except mysql.connector.Error as err:
        logger.error(f"Database connection failed: {err}")
        return None

def init_database():
    """Initialize database tables"""
    connection = get_db_connection()
    if not connection:
        logger.error("Cannot initialize database - no connection")
        return False
    
    try:
        cursor = connection.cursor()
        
        # Voice sessions table (tracks join/leave times)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS voice_sessions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                username VARCHAR(255) NOT NULL,
                channel_name VARCHAR(255) NOT NULL,
                channel_id BIGINT NOT NULL,
                join_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                leave_time TIMESTAMP NULL,
                duration_seconds INT NULL,
                INDEX idx_guild_user (guild_id, user_id),
                INDEX idx_join_time (join_time),
                INDEX idx_active_sessions (guild_id, user_id, leave_time)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        
        # User statistics table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_stats (
                id INT AUTO_INCREMENT PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                username VARCHAR(255) NOT NULL,
                total_joins INT DEFAULT 0,
                total_time_seconds BIGINT DEFAULT 0,
                last_join TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                channels_visited JSON,
                achievements JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY unique_guild_user (guild_id, user_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        
        # Daily stats for leaderboards
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_stats (
                id INT AUTO_INCREMENT PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                username VARCHAR(255) NOT NULL,
                date DATE NOT NULL,
                joins_count INT DEFAULT 0,
                time_seconds INT DEFAULT 0,
                channels_visited JSON,
                first_join_time TIME NULL,
                last_leave_time TIME NULL,
                UNIQUE KEY unique_guild_user_date (guild_id, user_id, date)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        
        connection.commit()
        logger.info("Database initialized successfully")
        return True
        
    except mysql.connector.Error as err:
        logger.error(f"Database initialization failed: {err}")
        return False
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

def format_duration(seconds):
    """Format duration in a human-readable way"""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        minutes = seconds // 60
        return f"{minutes}m"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        if minutes > 0:
            return f"{hours}h {minutes}m"
        return f"{hours}h"

def check_achievements(guild_id, user_id, session_data, user_stats):
    """Check and award achievements"""
    new_achievements = []
    current_achievements = user_stats.get('achievements', [])
    
    # Early Bird - First join today
    if session_data.get('is_first_today') and 'first_join_today' not in current_achievements:
        new_achievements.append('first_join_today')
    
    # Night Owl - Join after midnight
    join_hour = datetime.now().hour
    if join_hour >= 0 and join_hour < 6 and 'night_owl' not in current_achievements:
        new_achievements.append('night_owl')
    
    # Marathon Chatter - 4+ hours in voice today
    daily_time = session_data.get('daily_time_seconds', 0)
    if daily_time >= 14400 and 'marathon_chatter' not in current_achievements:  # 4 hours
        new_achievements.append('marathon_chatter')
    
    # Social Butterfly - 5 different channels in one day
    daily_channels = session_data.get('daily_channels', [])
    if len(daily_channels) >= 5 and 'social_butterfly' not in current_achievements:
        new_achievements.append('social_butterfly')
    
    # Loyal Friend - 100 total joins
    if user_stats.get('total_joins', 0) >= 100 and 'loyal_friend' not in current_achievements:
        new_achievements.append('loyal_friend')
    
    # Speed Demon - Quick in and out
    if session_data.get('duration', 0) <= 30 and 'speed_demon' not in current_achievements:
        new_achievements.append('speed_demon')
    
    return new_achievements

async def log_voice_join(member, channel):
    """Log voice channel join to database"""
    connection = get_db_connection()
    if not connection:
        return False
    
    try:
        cursor = connection.cursor()
        
        # Insert new session
        cursor.execute("""
            INSERT INTO voice_sessions (guild_id, user_id, username, channel_name, channel_id)
            VALUES (%s, %s, %s, %s, %s)
        """, (member.guild.id, member.id, member.display_name, channel.name, channel.id))
        
        session_id = cursor.lastrowid
        
        # Update user stats
        cursor.execute("""
            INSERT INTO user_stats (guild_id, user_id, username, total_joins, channels_visited, achievements)
            VALUES (%s, %s, %s, 1, %s, %s)
            ON DUPLICATE KEY UPDATE
            total_joins = total_joins + 1,
            username = VALUES(username),
            last_join = NOW(),
            channels_visited = JSON_MERGE_PATCH(
                COALESCE(channels_visited, '{}'),
                JSON_OBJECT(%s, COALESCE(JSON_EXTRACT(channels_visited, %s), 0) + 1)
            )
        """, (
            member.guild.id, member.id, member.display_name,
            json.dumps({channel.name: 1}),
            json.dumps([]),
            channel.name, f'$."{channel.name}"'
        ))
        
        # Update daily stats
        today = datetime.now().date()
        cursor.execute("""
            INSERT INTO daily_stats (guild_id, user_id, username, date, joins_count, channels_visited, first_join_time)
            VALUES (%s, %s, %s, %s, 1, %s, %s)
            ON DUPLICATE KEY UPDATE
            joins_count = joins_count + 1,
            username = VALUES(username),
            channels_visited = JSON_MERGE_PATCH(
                COALESCE(channels_visited, '{}'),
                JSON_OBJECT(%s, COALESCE(JSON_EXTRACT(channels_visited, %s), 0) + 1)
            ),
            first_join_time = COALESCE(first_join_time, VALUES(first_join_time))
        """, (
            member.guild.id, member.id, member.display_name, today,
            json.dumps([channel.name]),
            datetime.now().time(),
            channel.name, f'$."{channel.name}"'
        ))
        
        connection.commit()
        logger.info(f"Logged join: {member.display_name} -> {channel.name}")
        return session_id
        
    except mysql.connector.Error as err:
        logger.error(f"Failed to log voice join: {err}")
        return False
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

async def log_voice_leave(member, channel, join_time):
    """Log voice channel leave and calculate duration"""
    connection = get_db_connection()
    if not connection:
        return None
    
    try:
        cursor = connection.cursor()
        
        # Find the most recent session for this user
        cursor.execute("""
            SELECT id, join_time FROM voice_sessions
            WHERE guild_id = %s AND user_id = %s AND channel_id = %s AND leave_time IS NULL
            ORDER BY join_time DESC LIMIT 1
        """, (member.guild.id, member.id, channel.id))
        
        result = cursor.fetchone()
        if not result:
            return None
        
        session_id, db_join_time = result
        leave_time = datetime.now()
        duration = int((leave_time - db_join_time).total_seconds())
        
        # Update session with leave time
        cursor.execute("""
            UPDATE voice_sessions
            SET leave_time = %s, duration_seconds = %s
            WHERE id = %s
        """, (leave_time, duration, session_id))
        
        # Update user total time
        cursor.execute("""
            UPDATE user_stats
            SET total_time_seconds = total_time_seconds + %s
            WHERE guild_id = %s AND user_id = %s
        """, (duration, member.guild.id, member.id))
        
        # Update daily stats
        today = datetime.now().date()
        cursor.execute("""
            UPDATE daily_stats
            SET time_seconds = time_seconds + %s, last_leave_time = %s
            WHERE guild_id = %s AND user_id = %s AND date = %s
        """, (duration, leave_time.time(), member.guild.id, member.id, today))
        
        connection.commit()
        return duration
        
    except mysql.connector.Error as err:
        logger.error(f"Failed to log voice leave: {err}")
        return None
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

def get_first_text_channel(guild):
    """Get the first available text channel in the guild"""
    for channel in guild.text_channels:
        if channel.permissions_for(guild.me).send_messages:
            return channel
    return None

@bot.event
async def on_ready():
    """Bot startup event"""
    logger.info(f'{bot.user} has connected to Discord!')
    logger.info(f'Bot is in {len(bot.guilds)} guild(s)')
    
    # Initialize database
    if init_database():
        logger.info("Database ready!")
    else:
        logger.error("Database initialization failed!")
    
    # Start daily stats task
    daily_leaderboard.start()
    
    # Sync slash commands
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} command(s)")
    except Exception as e:
        logger.error(f"Failed to sync commands: {e}")

# Track active voice sessions for duration calculation
active_sessions = {}

@bot.event
async def on_voice_state_update(member, before, after):
    """Handle voice state changes - the heart of our bot!"""
    # Don't track bots
    if member.bot:
        return
    
    guild = member.guild
    channel = get_first_text_channel(guild)
    
    if channel is None:
        logger.warning(f"No text channel available in {guild.name}")
        return
    
    # User joined a voice channel (from nothing)
    if before.channel is None and after.channel is not None:
        # Store session start time
        session_key = f"{guild.id}_{member.id}_{after.channel.id}"
        active_sessions[session_key] = datetime.now()
        
        # Log to database
        session_id = await log_voice_join(member, after.channel)
        
        # Create rich embed message
        embed = discord.Embed(
            description=random.choice(JOIN_MESSAGES).format(
                user=member.display_name, 
                channel=after.channel.name
            ),
            color=0x00ff00,
            timestamp=datetime.now()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"Join #{session_id}" if session_id else "FunkBot")
        
        try:
            message = await channel.send(embed=embed, delete_after=300)
            await message.add_reaction("👋")
            logger.info(f"Announced join: {member.display_name} -> {after.channel.name}")
        except discord.errors.Forbidden:
            logger.error(f"No permission to send messages in {channel.name if channel else 'unknown channel'}")
        except Exception as e:
            logger.error(f"Failed to announce join: {e}")
    
    # User left a voice channel (to nothing)
    elif before.channel is not None and after.channel is None:
        session_key = f"{guild.id}_{member.id}_{before.channel.id}"
        join_time = active_sessions.pop(session_key, None)
        
        if join_time:
            duration = await log_voice_leave(member, before.channel, join_time)
            
            if duration and duration > 60:  # Only announce if they were there for more than 1 minute
                embed = discord.Embed(
                    description=random.choice(LEAVE_MESSAGES).format(
                        user=member.display_name,
                        channel=before.channel.name,
                        duration=format_duration(duration)
                    ),
                    color=0xff6b6b,
                    timestamp=datetime.now()
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                embed.set_footer(text="FunkBot")
                
                try:
                    message = await channel.send(embed=embed, delete_after=180)
                    await message.add_reaction("👋")
                    logger.info(f"Announced leave: {member.display_name} <- {before.channel.name} ({format_duration(duration)})")
                except Exception as e:
                    logger.error(f"Failed to announce leave: {e}")
    
    # User switched voice channels (from one channel to another)
    elif before.channel is not None and after.channel is not None and before.channel != after.channel:
        # Handle channel switch as both leave and join
        session_key_old = f"{guild.id}_{member.id}_{before.channel.id}"
        join_time = active_sessions.pop(session_key_old, None)
        
        if join_time:
            duration = await log_voice_leave(member, before.channel, join_time)
            
            if duration and duration > 10:  # Only announce if they were there for more than 10 seconds
                embed = discord.Embed(
                    description=f"🔄 **{member.display_name}** moved from **{before.channel.name}** to **{after.channel.name}** (was there {format_duration(duration)})",
                    color=0xffa500,
                    timestamp=datetime.now()
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                embed.set_footer(text="FunkBot")
                
                try:
                    message = await channel.send(embed=embed, delete_after=240)
                    await message.add_reaction("🔄")
                    logger.info(f"Announced channel switch: {member.display_name} {before.channel.name} -> {after.channel.name} ({format_duration(duration)})")
                except Exception as e:
                    logger.error(f"Failed to announce channel switch: {e}")
        
        # Now handle the new channel join
        session_key_new = f"{guild.id}_{member.id}_{after.channel.id}"
        active_sessions[session_key_new] = datetime.now()
        
        session_id = await log_voice_join(member, after.channel)
        
        # Don't announce the join part of a switch to avoid spam
        logger.info(f"Logged channel switch join: {member.display_name} -> {after.channel.name}")
# Slash Commands
@bot.tree.command(name="stats", description="View your voice chat statistics")
async def stats(interaction: discord.Interaction, user: Optional[discord.Member] = None):
    """Show voice statistics for a user"""
    target_user = user or interaction.user
    
    connection = get_db_connection()
    if not connection:
        await interaction.response.send_message("❌ Database connection failed!", ephemeral=True)
        return
    
    try:
        cursor = connection.cursor(dictionary=True)
        
        # Get user stats
        cursor.execute("""
            SELECT total_joins, total_time_seconds, channels_visited, achievements, last_join
            FROM user_stats
            WHERE guild_id = %s AND user_id = %s
        """, (interaction.guild_id, target_user.id))
        
        stats = cursor.fetchone()
        
        if not stats:
            await interaction.response.send_message(
                f"No voice activity found for {target_user.display_name}!", 
                ephemeral=True
            )
            return
        
        # Get today's stats
        cursor.execute("""
            SELECT joins_count, time_seconds, channels_visited
            FROM daily_stats
            WHERE guild_id = %s AND user_id = %s AND date = CURDATE()
        """, (interaction.guild_id, target_user.id))
        
        daily = cursor.fetchone() or {}
        
        # Create stats embed
        embed = discord.Embed(
            title=f"📊 Voice Stats for {target_user.display_name}",
            color=0x7289da,
            timestamp=datetime.now()
        )
        
        embed.set_thumbnail(url=target_user.display_avatar.url)
        
        # All-time stats
        embed.add_field(
            name="🏆 All Time",
            value=f"**Joins:** {stats['total_joins']:,}\n"
                  f"**Time:** {format_duration(stats['total_time_seconds'])}\n"
                  f"**Channels:** {len(json.loads(stats['channels_visited'] or '{}'))}"
        )
        
        # Today's stats
        embed.add_field(
            name="📅 Today",
            value=f"**Joins:** {daily.get('joins_count', 0)}\n"
                  f"**Time:** {format_duration(daily.get('time_seconds', 0))}\n"
                  f"**Channels:** {len(json.loads(daily.get('channels_visited', '[]') or '[]'))}"
        )
        
        # Achievements
        achievements = json.loads(stats['achievements'] or '[]')
        if achievements:
            achievement_text = "\n".join([
                f"{ACHIEVEMENTS[a]['emoji']} {ACHIEVEMENTS[a]['name']}"
                for a in achievements if a in ACHIEVEMENTS
            ])
            embed.add_field(
                name="🏅 Achievements",
                value=achievement_text[:1024] if achievement_text else "None yet!",
                inline=False
            )
        
        embed.set_footer(text="FunkBot Stats")
        
        await interaction.response.send_message(embed=embed)
        
    except Exception as e:
        logger.error(f"Stats command error: {e}")
        await interaction.response.send_message("❌ Error fetching stats!", ephemeral=True)
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

@bot.tree.command(name="leaderboard", description="View voice chat leaderboard")
async def leaderboard(interaction: discord.Interaction, timeframe: str = "today"):
    """Show voice leaderboard"""
    await interaction.response.defer()
    
    connection = get_db_connection()
    if not connection:
        await interaction.followup.send("❌ Database connection failed!")
        return
    
    try:
        cursor = connection.cursor(dictionary=True)
        
        if timeframe.lower() == "today":
            cursor.execute("""
                SELECT username, joins_count, time_seconds
                FROM daily_stats
                WHERE guild_id = %s AND date = CURDATE()
                ORDER BY time_seconds DESC, joins_count DESC
                LIMIT 10
            """, (interaction.guild_id,))
            title = "🏆 Today's Voice Leaderboard"
        else:
            cursor.execute("""
                SELECT username, total_joins, total_time_seconds
                FROM user_stats
                WHERE guild_id = %s
                ORDER BY total_time_seconds DESC, total_joins DESC
                LIMIT 10
            """, (interaction.guild_id,))
            title = "🏆 All-Time Voice Leaderboard"
        
        results = cursor.fetchall()
        
        if not results:
            await interaction.followup.send("No voice activity found!")
            return
        
        embed = discord.Embed(title=title, color=0xffd700, timestamp=datetime.now())
        
        medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
        
        leaderboard_text = ""
        for i, user in enumerate(results):
            if timeframe.lower() == "today":
                time_val = user['time_seconds']
                joins_val = user['joins_count']
            else:
                time_val = user['total_time_seconds']
                joins_val = user['total_joins']
            
            leaderboard_text += (
                f"{medals[i]} **{user['username']}**\n"
                f"    ⏱️ {format_duration(time_val)} • 🔄 {joins_val} joins\n\n"
            )
        
        embed.description = leaderboard_text
        embed.set_footer(text="FunkBot Leaderboard")
        
        await interaction.followup.send(embed=embed)
        
    except Exception as e:
        logger.error(f"Leaderboard command error: {e}")
        await interaction.followup.send("❌ Error fetching leaderboard!")
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

@tasks.loop(hours=24)
async def daily_leaderboard():
    """Post daily leaderboard at midnight"""
    await bot.wait_until_ready()
    
    for guild in bot.guilds:
        channel = get_first_text_channel(guild)
        if not channel:
            continue
        
        # Get yesterday's stats
        connection = get_db_connection()
        if not connection:
            continue
        
        try:
            cursor = connection.cursor(dictionary=True)
            yesterday = (datetime.now() - timedelta(days=1)).date()
            
            cursor.execute("""
                SELECT username, joins_count, time_seconds
                FROM daily_stats
                WHERE guild_id = %s AND date = %s AND time_seconds > 300
                ORDER BY time_seconds DESC
                LIMIT 5
            """, (guild.id, yesterday))
            
            results = cursor.fetchall()
            
            if results:
                embed = discord.Embed(
                    title=f"🌙 Yesterday's Voice Champions ({yesterday})",
                    color=0x9b59b6,
                    timestamp=datetime.now()
                )
                
                medals = ["🥇", "🥈", "🥉", "🏅", "🏅"]
                description = ""
                
                for i, user in enumerate(results):
                    description += (
                        f"{medals[i]} **{user['username']}** - "
                        f"{format_duration(user['time_seconds'])} "
                        f"({user['joins_count']} joins)\n"
                    )
                
                embed.description = description
                embed.set_footer(text="Daily recap by FunkBot")
                
                await channel.send(embed=embed)
                
        except Exception as e:
            logger.error(f"Daily leaderboard error: {e}")
        finally:
            if connection.is_connected():
                cursor.close()
                connection.close()

@bot.event
async def on_error(event, *args, **kwargs):
    """Global error handler"""
    logger.error(f"An error occurred in {event}: {args}")

# Health check for Docker
async def health_check():
    """Simple health check endpoint"""
    return bot.is_ready()

if __name__ == "__main__":
    # Get Discord token
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        logger.error("DISCORD_TOKEN environment variable not set!")
        exit(1)
    
    # Run the bot
    try:
        bot.run(token, log_handler=None)
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        exit(1)
