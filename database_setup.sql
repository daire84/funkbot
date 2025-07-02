-- FunkBot Database Setup Script
-- Run this in MariaDB via Adminer (port 8880)

DROP DATABASE IF EXISTS funkbot_db;
CREATE DATABASE funkbot_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

DROP USER IF EXISTS 'funkbot_user'@'%';
CREATE USER 'funkbot_user'@'%' IDENTIFIED BY 'YourSecurePassword123!';

GRANT ALL PRIVILEGES ON funkbot_db.* TO 'funkbot_user'@'%';
FLUSH PRIVILEGES;

SELECT 'FunkBot database setup complete!' as result;
