/*M!999999\- enable the sandbox mode */ 
-- MariaDB dump 10.19  Distrib 10.11.11-MariaDB, for debian-linux-gnu (x86_64)
--
-- Host: localhost    Database: DB_discordbot
-- ------------------------------------------------------
-- Server version	10.11.11-MariaDB-0+deb12u1

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `absence_messages`
--

DROP TABLE IF EXISTS `absence_messages`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `absence_messages` (
  `guild_id` bigint(20) unsigned NOT NULL,
  `message_id` bigint(20) unsigned NOT NULL,
  `member_id` bigint(20) unsigned NOT NULL,
  `created_at` datetime(6) NOT NULL DEFAULT current_timestamp(6),
  `return_date` datetime(6) DEFAULT NULL,
  PRIMARY KEY (`guild_id`,`message_id`),
  KEY `idx_guild_member` (`guild_id`,`member_id`),
  KEY `idx_return_date` (`guild_id`,`return_date`),
  KEY `idx_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Absence request messages tracking';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `contracts`
--

DROP TABLE IF EXISTS `contracts`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `contracts` (
  `guild_id` bigint(20) NOT NULL,
  `message_id` bigint(20) NOT NULL,
  PRIMARY KEY (`guild_id`),
  CONSTRAINT `fk_contracts_guild` FOREIGN KEY (`guild_id`) REFERENCES `guild_settings` (`guild_id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Guild contract messages';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `dynamic_voice_channels`
--

DROP TABLE IF EXISTS `dynamic_voice_channels`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `dynamic_voice_channels` (
  `channel_id` bigint(20) NOT NULL,
  `guild_id` bigint(20) NOT NULL,
  `created_at` timestamp NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`channel_id`),
  KEY `idx_dynamic_voice_guild` (`guild_id`),
  KEY `idx_dynamic_voice_created` (`created_at`),
  CONSTRAINT `fk_dynamic_voice_guild` FOREIGN KEY (`guild_id`) REFERENCES `guild_settings` (`guild_id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Temporary voice channels created by users';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `epic_items_scraping_history`
--

DROP TABLE IF EXISTS `epic_items_scraping_history`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `epic_items_scraping_history` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `scraping_date` timestamp NULL DEFAULT current_timestamp(),
  `items_scraped` int(11) NOT NULL,
  `items_added` int(11) DEFAULT 0,
  `items_updated` int(11) DEFAULT 0,
  `items_deleted` int(11) DEFAULT 0,
  `status` enum('success','partial','error') NOT NULL,
  `error_message` text DEFAULT NULL,
  `execution_time_seconds` int(11) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_scraping_date` (`scraping_date`),
  KEY `idx_status` (`status`)
) ENGINE=InnoDB AUTO_INCREMENT=19 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `epic_items_t2`
--

DROP TABLE IF EXISTS `epic_items_t2`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `epic_items_t2` (
  `item_id` varchar(100) NOT NULL,
  `item_type` varchar(50) NOT NULL,
  `item_category` varchar(50) NOT NULL,
  `item_name_en` varchar(255) NOT NULL,
  `item_name_fr` varchar(255) NOT NULL,
  `item_name_es` varchar(255) NOT NULL,
  `item_name_de` varchar(255) NOT NULL,
  `item_url` text NOT NULL,
  `item_icon_url` text DEFAULT NULL,
  `created_at` timestamp NULL DEFAULT current_timestamp(),
  `updated_at` timestamp NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`item_id`),
  KEY `idx_item_type` (`item_type`),
  KEY `idx_item_category` (`item_category`),
  KEY `idx_type_category` (`item_type`,`item_category`),
  FULLTEXT KEY `idx_name_en` (`item_name_en`),
  FULLTEXT KEY `idx_name_fr` (`item_name_fr`),
  FULLTEXT KEY `idx_name_es` (`item_name_es`),
  FULLTEXT KEY `idx_name_de` (`item_name_de`),
  FULLTEXT KEY `idx_all_names` (`item_name_en`,`item_name_fr`,`item_name_es`,`item_name_de`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Temporary table structure for view `epic_items_t2_view`
--

DROP TABLE IF EXISTS `epic_items_t2_view`;
/*!50001 DROP VIEW IF EXISTS `epic_items_t2_view`*/;
SET @saved_cs_client     = @@character_set_client;
SET character_set_client = utf8mb4;
/*!50001 CREATE VIEW `epic_items_t2_view` AS SELECT
 1 AS `item_id`,
  1 AS `item_type`,
  1 AS `item_category`,
  1 AS `item_name_en`,
  1 AS `item_name_fr`,
  1 AS `item_name_es`,
  1 AS `item_name_de`,
  1 AS `item_url`,
  1 AS `item_icon_url`,
  1 AS `created_at`,
  1 AS `updated_at`,
  1 AS `full_category`,
  1 AS `has_icon` */;
SET character_set_client = @saved_cs_client;

--
-- Table structure for table `events_calendar`
--

DROP TABLE IF EXISTS `events_calendar`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `events_calendar` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `game_id` int(11) NOT NULL DEFAULT 1,
  `name` varchar(255) NOT NULL,
  `day` enum('Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday') NOT NULL,
  `time` time NOT NULL,
  `duration` int(11) NOT NULL DEFAULT 0 COMMENT 'Event duration in minutes',
  `week` enum('all','odd','even') NOT NULL,
  `dkp_value` int(11) NOT NULL,
  `dkp_ins` int(11) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_events_calendar_day` (`day`),
  KEY `idx_events_calendar_time` (`time`),
  KEY `idx_events_calendar_game` (`game_id`),
  CONSTRAINT `fk_events_calendar_game` FOREIGN KEY (`game_id`) REFERENCES `games_list` (`id`) ON DELETE NO ACTION ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=12 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Recurring event templates and schedules';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `events_data`
--

DROP TABLE IF EXISTS `events_data`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `events_data` (
  `guild_id` bigint(20) NOT NULL,
  `event_id` bigint(20) NOT NULL,
  `game_id` int(11) NOT NULL DEFAULT 1 COMMENT 'Game type ID (FK to games_list)',
  `name` varchar(255) NOT NULL COMMENT 'Event display name',
  `event_date` date NOT NULL,
  `event_time` time NOT NULL,
  `duration` smallint(6) NOT NULL COMMENT 'Event duration in minutes',
  `dkp_value` smallint(6) NOT NULL COMMENT 'DKP reward for attendance',
  `dkp_ins` smallint(6) NOT NULL COMMENT 'DKP reward for registration',
  `status` varchar(50) NOT NULL COMMENT 'Event status (planned, confirmed, closed, cancelled)',
  `initial_members` longtext DEFAULT NULL CHECK (json_valid(`initial_members`)),
  `registrations` longtext DEFAULT '{"presence": [], "tentative": [], "absence": []}',
  `actual_presence` longtext DEFAULT NULL CHECK (json_valid(`actual_presence`)),
  PRIMARY KEY (`guild_id`,`event_id`),
  KEY `idx_events_data_date` (`event_date`),
  KEY `idx_events_data_status` (`status`),
  KEY `idx_events_data_game` (`game_id`),
  KEY `idx_events_data_guild_date` (`guild_id`,`event_date`),
  KEY `idx_events_data_guild_date_status` (`guild_id`,`event_date`,`status`),
  KEY `idx_events_data_guild_game` (`guild_id`,`game_id`),
  KEY `idx_events_data_date_status` (`event_date`,`status`),
  CONSTRAINT `fk_events_data_game` FOREIGN KEY (`game_id`) REFERENCES `games_list` (`id`) ON DELETE NO ACTION ON UPDATE CASCADE,
  CONSTRAINT `fk_events_data_guild` FOREIGN KEY (`guild_id`) REFERENCES `guild_settings` (`guild_id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `chk_event_status` CHECK (`status` in ('planned','confirmed','closed','canceled','cancelled'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Individual event instances with registration data';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `games_list`
--

DROP TABLE IF EXISTS `games_list`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `games_list` (
  `id` int(11) NOT NULL AUTO_INCREMENT COMMENT 'Unique game identifier',
  `game_name` varchar(30) NOT NULL COMMENT 'Official game title/name',
  `max_members` tinyint(4) DEFAULT NULL COMMENT 'Maximum members per group/party in this game',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Supported games and their configurations';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `guild_channels`
--

DROP TABLE IF EXISTS `guild_channels`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `guild_channels` (
  `guild_id` bigint(20) NOT NULL,
  `rules_channel` bigint(20) DEFAULT NULL COMMENT 'Channel for guild rules display',
  `rules_message` bigint(20) DEFAULT NULL COMMENT 'Message ID containing guild rules',
  `announcements_channel` bigint(20) DEFAULT NULL COMMENT 'Channel for guild announcements',
  `voice_tavern_channel` bigint(20) DEFAULT NULL COMMENT 'Social voice channel for casual chat',
  `voice_war_channel` bigint(20) DEFAULT NULL COMMENT 'Voice channel for combat/war activities',
  `create_room_channel` bigint(20) DEFAULT NULL COMMENT 'Channel to trigger dynamic voice room creation',
  `events_channel` bigint(20) DEFAULT NULL COMMENT 'Channel for event announcements and scheduling',
  `members_channel` bigint(20) DEFAULT NULL COMMENT 'Main member list display channel',
  `members_m1` bigint(20) DEFAULT NULL COMMENT 'Member list message 1 (pagination)',
  `members_m2` bigint(20) DEFAULT NULL COMMENT 'Member list message 2 (pagination)',
  `members_m3` bigint(20) DEFAULT NULL COMMENT 'Member list message 3 (pagination)',
  `members_m4` bigint(20) DEFAULT NULL COMMENT 'Member list message 4 (pagination)',
  `members_m5` bigint(20) DEFAULT NULL COMMENT 'Member list message 5 (pagination)',
  `groups_channel` bigint(20) DEFAULT NULL COMMENT 'Channel for group management and display',
  `statics_channel` bigint(20) DEFAULT NULL COMMENT 'Channel for static group displays',
  `statics_message` bigint(20) DEFAULT NULL COMMENT 'Message ID for static groups list',
  `abs_channel` bigint(20) DEFAULT NULL COMMENT 'Channel for absence requests and tracking',
  `loot_channel` bigint(20) DEFAULT NULL COMMENT 'Channel for loot distribution and DKP',
  `loot_message` bigint(20) DEFAULT NULL COMMENT 'Loot message ID',
  `tuto_channel` bigint(20) DEFAULT NULL COMMENT 'Channel for tutorials and guides',
  `forum_allies_channel` bigint(20) DEFAULT NULL COMMENT 'Forum channel for ally guild communications',
  `forum_friends_channel` bigint(20) DEFAULT NULL COMMENT 'Forum channel for friendly guild communications',
  `forum_diplomats_channel` bigint(20) DEFAULT NULL COMMENT 'Forum channel for diplomatic discussions',
  `forum_recruitment_channel` bigint(20) DEFAULT NULL COMMENT 'Forum channel for recruitment posts',
  `forum_members_channel` bigint(20) DEFAULT NULL COMMENT 'Forum channel for member discussions',
  `notifications_channel` bigint(20) DEFAULT NULL COMMENT 'Channel for bot notifications and alerts',
  `external_recruitment_cat` bigint(20) DEFAULT NULL COMMENT 'External recruitment category ID',
  `category_diplomat` bigint(20) DEFAULT NULL COMMENT 'Diplomat category channel ID',
  `external_recruitment_channel` bigint(20) DEFAULT NULL COMMENT 'External recruitment channel ID',
  `external_recruitment_message` bigint(20) DEFAULT NULL COMMENT 'External recruitment message ID',
  `updated_at` timestamp NULL DEFAULT current_timestamp() ON UPDATE current_timestamp() COMMENT 'Last modification timestamp for channel configuration',
  PRIMARY KEY (`guild_id`),
  KEY `idx_guild_channels_statics_channel` (`statics_channel`),
  KEY `idx_guild_channels_statics_message` (`statics_message`),
  CONSTRAINT `fk_guild_channels_guild` FOREIGN KEY (`guild_id`) REFERENCES `guild_settings` (`guild_id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Discord channel IDs for each guild functionality';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `guild_ideal_staff`
--

DROP TABLE IF EXISTS `guild_ideal_staff`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `guild_ideal_staff` (
  `guild_id` bigint(20) NOT NULL COMMENT 'Discord guild ID (FK to guild_settings)',
  `class_name` varchar(50) NOT NULL COMMENT 'Character class/role name',
  `ideal_count` int(11) NOT NULL DEFAULT 0 COMMENT 'Target number of members for this class',
  `created_at` timestamp NULL DEFAULT current_timestamp() COMMENT 'Record creation timestamp',
  `updated_at` timestamp NULL DEFAULT current_timestamp() ON UPDATE current_timestamp() COMMENT 'Last modification timestamp',
  PRIMARY KEY (`guild_id`,`class_name`),
  KEY `idx_guild_ideal_staff_guild_class` (`guild_id`,`class_name`),
  CONSTRAINT `guild_ideal_staff_ibfk_1` FOREIGN KEY (`guild_id`) REFERENCES `guild_settings` (`guild_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Ideal class composition targets for guild optimization';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `guild_members`
--

DROP TABLE IF EXISTS `guild_members`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `guild_members` (
  `guild_id` bigint(20) NOT NULL,
  `member_id` bigint(20) NOT NULL,
  `username` varchar(64) DEFAULT NULL COMMENT 'User display name/nickname',
  `language` varchar(8) DEFAULT 'en-US' COMMENT 'User preferred language',
  `GS` int(11) DEFAULT NULL COMMENT 'Gear Score/Power Level',
  `build` text DEFAULT NULL COMMENT 'Character build URL or description',
  `weapons` varchar(16) DEFAULT NULL COMMENT 'Weapon combination codes',
  `DKP` decimal(10,2) DEFAULT NULL COMMENT 'Dragon Kill Points for loot distribution',
  `nb_events` int(11) DEFAULT NULL COMMENT 'Total events participated in',
  `registrations` int(11) DEFAULT 0 COMMENT 'Number of event registrations',
  `attendances` int(11) DEFAULT 0 COMMENT 'Number of event attendances',
  `class` varchar(32) DEFAULT NULL COMMENT 'Character class/role',
  PRIMARY KEY (`guild_id`,`member_id`),
  KEY `idx_guild_members_dkp` (`DKP` DESC),
  KEY `idx_guild_members_class` (`class`),
  CONSTRAINT `fk_guild_members_guild` FOREIGN KEY (`guild_id`) REFERENCES `guild_settings` (`guild_id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Guild member profiles and game statistics';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Temporary table structure for view `guild_overview`
--

DROP TABLE IF EXISTS `guild_overview`;
/*!50001 DROP VIEW IF EXISTS `guild_overview`*/;
SET @saved_cs_client     = @@character_set_client;
SET character_set_client = utf8mb4;
/*!50001 CREATE VIEW `guild_overview` AS SELECT
 1 AS `guild_id`,
  1 AS `guild_name`,
  1 AS `guild_lang`,
  1 AS `guild_game`,
  1 AS `guild_server`,
  1 AS `initialized`,
  1 AS `premium`,
  1 AS `created_at`,
  1 AS `total_members`,
  1 AS `static_groups_count`,
  1 AS `game_name` */;
SET character_set_client = @saved_cs_client;

--
-- Table structure for table `guild_ptb_settings`
--

DROP TABLE IF EXISTS `guild_ptb_settings`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `guild_ptb_settings` (
  `guild_id` bigint(20) NOT NULL COMMENT 'Discord main guild ID (FK to guild_settings)',
  `ptb_guild_id` bigint(20) NOT NULL COMMENT 'Discord PTB guild ID',
  `info_channel_id` bigint(20) NOT NULL COMMENT 'Info text channel ID in PTB',
  `g1_role_id` bigint(20) DEFAULT NULL COMMENT 'G1 role ID in PTB',
  `g1_channel_id` bigint(20) DEFAULT NULL COMMENT 'G1 voice channel ID in PTB',
  `g2_role_id` bigint(20) DEFAULT NULL COMMENT 'G2 role ID in PTB',
  `g2_channel_id` bigint(20) DEFAULT NULL COMMENT 'G2 voice channel ID in PTB',
  `g3_role_id` bigint(20) DEFAULT NULL COMMENT 'G3 role ID in PTB',
  `g3_channel_id` bigint(20) DEFAULT NULL COMMENT 'G3 voice channel ID in PTB',
  `g4_role_id` bigint(20) DEFAULT NULL COMMENT 'G4 role ID in PTB',
  `g4_channel_id` bigint(20) DEFAULT NULL COMMENT 'G4 voice channel ID in PTB',
  `g5_role_id` bigint(20) DEFAULT NULL COMMENT 'G5 role ID in PTB',
  `g5_channel_id` bigint(20) DEFAULT NULL COMMENT 'G5 voice channel ID in PTB',
  `g6_role_id` bigint(20) DEFAULT NULL COMMENT 'G6 role ID in PTB',
  `g6_channel_id` bigint(20) DEFAULT NULL COMMENT 'G6 voice channel ID in PTB',
  `g7_role_id` bigint(20) DEFAULT NULL COMMENT 'G7 role ID in PTB',
  `g7_channel_id` bigint(20) DEFAULT NULL COMMENT 'G7 voice channel ID in PTB',
  `g8_role_id` bigint(20) DEFAULT NULL COMMENT 'G8 role ID in PTB',
  `g8_channel_id` bigint(20) DEFAULT NULL COMMENT 'G8 voice channel ID in PTB',
  `g9_role_id` bigint(20) DEFAULT NULL COMMENT 'G9 role ID in PTB',
  `g9_channel_id` bigint(20) DEFAULT NULL COMMENT 'G9 voice channel ID in PTB',
  `g10_role_id` bigint(20) DEFAULT NULL COMMENT 'G10 role ID in PTB',
  `g10_channel_id` bigint(20) DEFAULT NULL COMMENT 'G10 voice channel ID in PTB',
  `g11_role_id` bigint(20) DEFAULT NULL COMMENT 'G11 role ID in PTB',
  `g11_channel_id` bigint(20) DEFAULT NULL COMMENT 'G11 voice channel ID in PTB',
  `g12_role_id` bigint(20) DEFAULT NULL COMMENT 'G12 role ID in PTB',
  `g12_channel_id` bigint(20) DEFAULT NULL COMMENT 'G12 voice channel ID in PTB',
  `created_at` timestamp NULL DEFAULT current_timestamp(),
  `updated_at` timestamp NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`guild_id`),
  UNIQUE KEY `uk_ptb_guild` (`ptb_guild_id`),
  CONSTRAINT `fk_guild_ptb_settings_guild` FOREIGN KEY (`guild_id`) REFERENCES `guild_settings` (`guild_id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='PTB (Public Test Build) Discord server settings and channel/role mappings';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `guild_roles`
--

DROP TABLE IF EXISTS `guild_roles`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `guild_roles` (
  `guild_id` bigint(20) NOT NULL,
  `guild_master` bigint(20) DEFAULT NULL COMMENT 'Guild leader role ID with full permissions',
  `officer` bigint(20) DEFAULT NULL COMMENT 'Officer role ID with management permissions',
  `guardian` bigint(20) DEFAULT NULL COMMENT 'Guardian role ID with moderation permissions',
  `members` bigint(20) DEFAULT NULL COMMENT 'Standard member role ID',
  `absent_members` bigint(20) DEFAULT NULL COMMENT 'Role for members marked as absent',
  `allies` bigint(20) DEFAULT NULL COMMENT 'Allied guild member role ID',
  `diplomats` bigint(20) DEFAULT NULL COMMENT 'Diplomatic representative role ID',
  `friends` bigint(20) DEFAULT NULL COMMENT 'Friendly guild member role ID',
  `applicant` bigint(20) DEFAULT NULL COMMENT 'Role for pending guild applicants',
  `config_ok` bigint(20) DEFAULT NULL COMMENT 'Role for members who completed configuration',
  `rules_ok` bigint(20) DEFAULT NULL COMMENT 'Role for members who acknowledged rules',
  `updated_at` timestamp NULL DEFAULT current_timestamp() ON UPDATE current_timestamp() COMMENT 'Last role configuration update timestamp',
  PRIMARY KEY (`guild_id`),
  CONSTRAINT `fk_guild_roles_guild` FOREIGN KEY (`guild_id`) REFERENCES `guild_settings` (`guild_id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Discord role IDs for guild permissions and hierarchy';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `guild_settings`
--

DROP TABLE IF EXISTS `guild_settings`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `guild_settings` (
  `guild_id` bigint(20) NOT NULL COMMENT 'Discord guild ID (primary key)',
  `guild_ptb` bigint(20) DEFAULT NULL COMMENT 'Discord PTB guild ID if applicable',
  `guild_name` varchar(30) NOT NULL COMMENT 'Guild display name',
  `guild_lang` varchar(5) NOT NULL COMMENT 'Guild language code (en-US, fr, es-ES, de, it)',
  `guild_game` smallint(6) DEFAULT NULL COMMENT 'Primary game ID (FK to games_list)',
  `guild_server` varchar(20) DEFAULT NULL COMMENT 'Game server name/region',
  `initialized` tinyint(1) DEFAULT 0 COMMENT 'Whether guild setup is complete',
  `premium` tinyint(1) DEFAULT 0 COMMENT 'Premium features enabled flag',
  `created_at` datetime DEFAULT current_timestamp(),
  `updated_at` datetime DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`guild_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Main guild configuration and settings';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `guild_static_groups`
--

DROP TABLE IF EXISTS `guild_static_groups`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `guild_static_groups` (
  `id` int(11) NOT NULL AUTO_INCREMENT COMMENT 'Unique static group identifier',
  `guild_id` bigint(20) NOT NULL COMMENT 'Discord guild ID (FK to guild_settings)',
  `group_name` varchar(100) NOT NULL COMMENT 'Display name of the static group',
  `leader_id` bigint(20) NOT NULL COMMENT 'Discord member ID of group leader',
  `created_at` timestamp NULL DEFAULT current_timestamp() COMMENT 'Group creation timestamp',
  `updated_at` timestamp NULL DEFAULT current_timestamp() ON UPDATE current_timestamp() COMMENT 'Last group modification timestamp',
  `is_active` tinyint(1) DEFAULT 1 COMMENT 'Whether group is currently active (1=active, 0=inactive)',
  PRIMARY KEY (`id`),
  UNIQUE KEY `unique_group_name` (`guild_id`,`group_name`),
  KEY `idx_guild_id` (`guild_id`),
  KEY `idx_leader_id` (`leader_id`),
  KEY `idx_active` (`is_active`),
  CONSTRAINT `fk_static_groups_guild` FOREIGN KEY (`guild_id`) REFERENCES `guild_settings` (`guild_id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=7 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Static group definitions and metadata';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `guild_static_members`
--

DROP TABLE IF EXISTS `guild_static_members`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `guild_static_members` (
  `id` int(11) NOT NULL AUTO_INCREMENT COMMENT 'Unique membership record identifier',
  `group_id` int(11) NOT NULL COMMENT 'Static group ID (FK to guild_static_groups)',
  `member_id` bigint(20) NOT NULL COMMENT 'Discord member ID (FK to guild_members)',
  `position_order` tinyint(4) DEFAULT 1 COMMENT 'Display order position within the group (1-based)',
  `joined_at` timestamp NULL DEFAULT current_timestamp() COMMENT 'Timestamp when member joined the group',
  PRIMARY KEY (`id`),
  UNIQUE KEY `unique_member_group` (`group_id`,`member_id`),
  KEY `idx_member_id` (`member_id`),
  KEY `idx_group_id` (`group_id`),
  KEY `idx_static_members_member_group` (`member_id`,`group_id`),
  CONSTRAINT `guild_static_members_ibfk_1` FOREIGN KEY (`group_id`) REFERENCES `guild_static_groups` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=10 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Static group membership with positions';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `loot_wishlist`
--

DROP TABLE IF EXISTS `loot_wishlist`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `loot_wishlist` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `guild_id` bigint(20) NOT NULL,
  `user_id` bigint(20) NOT NULL,
  `item_name` varchar(255) NOT NULL,
  `item_id` varchar(100) DEFAULT NULL,
  `priority` tinyint(4) DEFAULT 1,
  `created_at` timestamp NULL DEFAULT current_timestamp(),
  `updated_at` timestamp NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `unique_user_item` (`guild_id`,`user_id`,`item_name`),
  KEY `idx_guild_user` (`guild_id`,`user_id`),
  KEY `idx_guild_item` (`guild_id`,`item_name`),
  KEY `idx_item_id` (`item_id`),
  KEY `idx_created_at` (`created_at`),
  CONSTRAINT `fk_loot_wishlist_guild` FOREIGN KEY (`guild_id`) REFERENCES `guild_settings` (`guild_id`) ON DELETE CASCADE,
  CONSTRAINT `chk_priority` CHECK (`priority` in (1,2,3))
) ENGINE=InnoDB AUTO_INCREMENT=16 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Epic T2 items wishlist for guild members - max 3 items per user';
/*!40101 SET character_set_client = @saved_cs_client */;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_unicode_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_AUTO_CREATE_USER,NO_ENGINE_SUBSTITUTION' */ ;
DELIMITER ;;
/*!50003 CREATE*/ /*!50017 DEFINER=`USER_discordbot`@`localhost`*/ /*!50003 TRIGGER loot_wishlist_history_insert
AFTER INSERT ON loot_wishlist
FOR EACH ROW
BEGIN
    INSERT INTO loot_wishlist_history (
        guild_id, user_id, item_name, item_id, action, priority_new
    ) VALUES (
        NEW.guild_id, NEW.user_id, NEW.item_name, NEW.item_id, 'ADD', NEW.priority
    );
END */;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_unicode_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_AUTO_CREATE_USER,NO_ENGINE_SUBSTITUTION' */ ;
DELIMITER ;;
/*!50003 CREATE*/ /*!50017 DEFINER=`USER_discordbot`@`localhost`*/ /*!50003 TRIGGER loot_wishlist_history_update
AFTER UPDATE ON loot_wishlist
FOR EACH ROW
BEGIN
    INSERT INTO loot_wishlist_history (
        guild_id, user_id, item_name, item_id, action, priority_old, priority_new
    ) VALUES (
        NEW.guild_id, NEW.user_id, NEW.item_name, NEW.item_id, 'UPDATE', OLD.priority, NEW.priority
    );
END */;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_unicode_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_AUTO_CREATE_USER,NO_ENGINE_SUBSTITUTION' */ ;
DELIMITER ;;
/*!50003 CREATE*/ /*!50017 DEFINER=`USER_discordbot`@`localhost`*/ /*!50003 TRIGGER loot_wishlist_history_delete
AFTER DELETE ON loot_wishlist
FOR EACH ROW
BEGIN
    INSERT INTO loot_wishlist_history (
        guild_id, user_id, item_name, item_id, action, priority_old
    ) VALUES (
        OLD.guild_id, OLD.user_id, OLD.item_name, OLD.item_id, 'REMOVE', OLD.priority
    );
END */;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;

--
-- Table structure for table `loot_wishlist_history`
--

DROP TABLE IF EXISTS `loot_wishlist_history`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `loot_wishlist_history` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `guild_id` bigint(20) NOT NULL,
  `user_id` bigint(20) NOT NULL,
  `item_name` varchar(255) NOT NULL,
  `item_id` varchar(100) DEFAULT NULL,
  `action` enum('ADD','REMOVE','UPDATE') NOT NULL,
  `priority_old` tinyint(4) DEFAULT NULL,
  `priority_new` tinyint(4) DEFAULT NULL,
  `timestamp` timestamp NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `idx_guild_timestamp` (`guild_id`,`timestamp`),
  KEY `idx_user_timestamp` (`user_id`,`timestamp`),
  KEY `idx_item_timestamp` (`item_name`,`timestamp`),
  KEY `idx_action` (`action`),
  CONSTRAINT `fk_loot_wishlist_history_guild` FOREIGN KEY (`guild_id`) REFERENCES `guild_settings` (`guild_id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=29 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='History of wishlist changes for analytics and audit trail';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Temporary table structure for view `loot_wishlist_stats`
--

DROP TABLE IF EXISTS `loot_wishlist_stats`;
/*!50001 DROP VIEW IF EXISTS `loot_wishlist_stats`*/;
SET @saved_cs_client     = @@character_set_client;
SET character_set_client = utf8mb4;
/*!50001 CREATE VIEW `loot_wishlist_stats` AS SELECT
 1 AS `guild_id`,
  1 AS `item_name`,
  1 AS `item_id`,
  1 AS `demand_count`,
  1 AS `interested_users`,
  1 AS `avg_priority`,
  1 AS `first_request`,
  1 AS `last_request` */;
SET character_set_client = @saved_cs_client;

--
-- Temporary table structure for view `member_statistics`
--

DROP TABLE IF EXISTS `member_statistics`;
/*!50001 DROP VIEW IF EXISTS `member_statistics`*/;
SET @saved_cs_client     = @@character_set_client;
SET character_set_client = utf8mb4;
/*!50001 CREATE VIEW `member_statistics` AS SELECT
 1 AS `guild_id`,
  1 AS `member_id`,
  1 AS `username`,
  1 AS `class`,
  1 AS `GS`,
  1 AS `DKP`,
  1 AS `nb_events`,
  1 AS `registrations`,
  1 AS `attendances`,
  1 AS `attendance_rate`,
  1 AS `avg_dkp_per_event` */;
SET character_set_client = @saved_cs_client;

--
-- Table structure for table `pending_diplomat_validations`
--

DROP TABLE IF EXISTS `pending_diplomat_validations`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `pending_diplomat_validations` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `guild_id` bigint(20) NOT NULL,
  `member_id` bigint(20) NOT NULL,
  `guild_name` varchar(255) NOT NULL,
  `channel_id` bigint(20) NOT NULL,
  `message_id` bigint(20) NOT NULL,
  `status` enum('pending','completed','expired') NOT NULL DEFAULT 'pending',
  `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
  `completed_at` timestamp NULL DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `unique_validation` (`guild_id`,`member_id`,`guild_name`,`status`),
  KEY `idx_pending_validations_status` (`status`),
  KEY `idx_pending_validations_guild` (`guild_id`),
  KEY `idx_pending_validations_created` (`created_at`),
  CONSTRAINT `fk_diplomat_validations_guild` FOREIGN KEY (`guild_id`) REFERENCES `guild_settings` (`guild_id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=7 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Diplomat validation requests and status';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Temporary table structure for view `static_groups_with_members`
--

DROP TABLE IF EXISTS `static_groups_with_members`;
/*!50001 DROP VIEW IF EXISTS `static_groups_with_members`*/;
SET @saved_cs_client     = @@character_set_client;
SET character_set_client = utf8mb4;
/*!50001 CREATE VIEW `static_groups_with_members` AS SELECT
 1 AS `group_id`,
  1 AS `guild_id`,
  1 AS `group_name`,
  1 AS `leader_id`,
  1 AS `is_active`,
  1 AS `group_created_at`,
  1 AS `group_updated_at`,
  1 AS `member_count`,
  1 AS `member_ids`,
  1 AS `member_positions` */;
SET character_set_client = @saved_cs_client;

--
-- Table structure for table `user_setup`
--

DROP TABLE IF EXISTS `user_setup`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `user_setup` (
  `guild_id` bigint(20) NOT NULL,
  `user_id` bigint(20) NOT NULL,
  `nickname` varchar(32) DEFAULT NULL COMMENT 'User in-game nickname',
  `username` varchar(64) DEFAULT NULL COMMENT 'User display name/nickname',
  `locale` varchar(5) NOT NULL,
  `motif` varchar(32) NOT NULL,
  `friend_pseudo` varchar(32) DEFAULT NULL,
  `weapons` varchar(255) DEFAULT NULL,
  `guild_name` varchar(255) DEFAULT NULL,
  `guild_acronym` varchar(16) DEFAULT NULL,
  `gs` smallint(5) DEFAULT NULL,
  `playtime` varchar(64) DEFAULT NULL,
  `game_mode` varchar(64) DEFAULT NULL COMMENT 'User preferred game mode (PvE/PvP/Mixed)',
  PRIMARY KEY (`guild_id`,`user_id`),
  KEY `idx_user_setup_locale` (`locale`),
  KEY `idx_user_setup_motif` (`motif`),
  CONSTRAINT `fk_user_setup_guild` FOREIGN KEY (`guild_id`) REFERENCES `guild_settings` (`guild_id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='User registration and setup process data';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `weapons`
--

DROP TABLE IF EXISTS `weapons`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `weapons` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `game_id` int(11) NOT NULL DEFAULT 1,
  `name` varchar(100) NOT NULL,
  `code` varchar(10) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_weapons_game_code` (`game_id`,`code`),
  CONSTRAINT `fk_weapons_game` FOREIGN KEY (`game_id`) REFERENCES `games_list` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=9 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Available weapons per game';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `weapons_combinations`
--

DROP TABLE IF EXISTS `weapons_combinations`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `weapons_combinations` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `game_id` int(11) NOT NULL DEFAULT 1,
  `role` varchar(50) NOT NULL,
  `weapon1` varchar(10) NOT NULL,
  `weapon2` varchar(10) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_weapons_combinations_game_role` (`game_id`,`role`),
  CONSTRAINT `fk_weapons_combinations_game` FOREIGN KEY (`game_id`) REFERENCES `games_list` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=28 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Valid weapon combinations per role';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `welcome_messages`
--

DROP TABLE IF EXISTS `welcome_messages`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `welcome_messages` (
  `guild_id` bigint(20) NOT NULL,
  `member_id` bigint(20) NOT NULL,
  `channel_id` bigint(20) NOT NULL,
  `message_id` bigint(20) NOT NULL,
  `created_at` timestamp NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`guild_id`,`member_id`),
  KEY `idx_welcome_messages_channel` (`channel_id`),
  KEY `idx_welcome_messages_created` (`created_at`),
  KEY `idx_welcome_messages_message` (`message_id`),
  CONSTRAINT `fk_welcome_messages_guild` FOREIGN KEY (`guild_id`) REFERENCES `guild_settings` (`guild_id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Welcome message tracking for new members';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping events for database 'DB_discordbot'
--

--
-- Dumping routines for database 'DB_discordbot'
--
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_AUTO_CREATE_USER,NO_ENGINE_SUBSTITUTION' */ ;
/*!50003 DROP FUNCTION IF EXISTS `GetItemName` */;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_unicode_ci */ ;
DELIMITER ;;
CREATE DEFINER=`USER_discordbot`@`localhost` FUNCTION `GetItemName`(p_item_id VARCHAR(100),
    p_language VARCHAR(5)
) RETURNS varchar(255) CHARSET utf8mb4 COLLATE utf8mb4_general_ci
    READS SQL DATA
    DETERMINISTIC
BEGIN
    DECLARE item_name VARCHAR(255);
    
    -- Utilisation de CASE pour éviter le SQL dynamique dans une fonction
    SELECT 
        CASE p_language
            WHEN 'en' THEN item_name_en
            WHEN 'fr' THEN item_name_fr
            WHEN 'es' THEN item_name_es
            WHEN 'de' THEN item_name_de
            ELSE item_name_en -- Par défaut, retourne l'anglais
        END INTO item_name
    FROM epic_items_t2 
    WHERE item_id = p_item_id;
    
    RETURN item_name;
END ;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_AUTO_CREATE_USER,NO_ENGINE_SUBSTITUTION' */ ;
/*!50003 DROP PROCEDURE IF EXISTS `CheckWishlistLimit` */;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_unicode_ci */ ;
DELIMITER ;;
CREATE DEFINER=`USER_discordbot`@`localhost` PROCEDURE `CheckWishlistLimit`(
    IN p_guild_id BIGINT,
    IN p_user_id BIGINT
)
BEGIN
    DECLARE item_count INT DEFAULT 0;
    
    SELECT COUNT(*) INTO item_count 
    FROM loot_wishlist 
    WHERE guild_id = p_guild_id AND user_id = p_user_id;
    
    IF item_count >= 3 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'User already has 3 items in wishlist';
    END IF;
END ;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_AUTO_CREATE_USER,NO_ENGINE_SUBSTITUTION' */ ;
/*!50003 DROP PROCEDURE IF EXISTS `GetItemsByTypeAndLanguage` */;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_unicode_ci */ ;
DELIMITER ;;
CREATE DEFINER=`USER_discordbot`@`localhost` PROCEDURE `GetItemsByTypeAndLanguage`(
    IN p_item_type VARCHAR(50),
    IN p_language VARCHAR(5)
)
BEGIN
    SET @sql = CONCAT(
        'SELECT item_id, item_type, item_category, item_name_', p_language, 
        ' AS item_name, item_icon_url, item_url ',
        'FROM epic_items_t2 '
    );
    
    IF p_item_type IS NOT NULL AND p_item_type != '' THEN
        SET @sql = CONCAT(@sql, 'WHERE item_type = ''', p_item_type, ''' ');
    END IF;
    
    SET @sql = CONCAT(@sql, 'ORDER BY item_category, item_name_', p_language);
    
    PREPARE stmt FROM @sql;
    EXECUTE stmt;
    DEALLOCATE PREPARE stmt;
END ;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'STRICT_TRANS_TABLES,ERROR_FOR_DIVISION_BY_ZERO,NO_AUTO_CREATE_USER,NO_ENGINE_SUBSTITUTION' */ ;
/*!50003 DROP PROCEDURE IF EXISTS `SearchItemsByName` */;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_unicode_ci */ ;
DELIMITER ;;
CREATE DEFINER=`USER_discordbot`@`localhost` PROCEDURE `SearchItemsByName`(
    IN p_search_term VARCHAR(255)
)
BEGIN
    SELECT DISTINCT
        item_id,
        item_type,
        item_category,
        item_name_en,
        item_name_fr,
        item_name_es,
        item_name_de,
        item_icon_url,
        item_url,
        CASE
            WHEN item_name_en LIKE CONCAT('%', p_search_term, '%') THEN 'en'
            WHEN item_name_fr LIKE CONCAT('%', p_search_term, '%') THEN 'fr'
            WHEN item_name_es LIKE CONCAT('%', p_search_term, '%') THEN 'es'
            WHEN item_name_de LIKE CONCAT('%', p_search_term, '%') THEN 'de'
        END AS matched_language
    FROM epic_items_t2
    WHERE 
        item_name_en LIKE CONCAT('%', p_search_term, '%') OR
        item_name_fr LIKE CONCAT('%', p_search_term, '%') OR
        item_name_es LIKE CONCAT('%', p_search_term, '%') OR
        item_name_de LIKE CONCAT('%', p_search_term, '%')
    ORDER BY 
        CASE
            WHEN item_name_en LIKE CONCAT(p_search_term, '%') THEN 1
            WHEN item_name_fr LIKE CONCAT(p_search_term, '%') THEN 1
            WHEN item_name_es LIKE CONCAT(p_search_term, '%') THEN 1
            WHEN item_name_de LIKE CONCAT(p_search_term, '%') THEN 1
            ELSE 2
        END,
        item_type,
        item_category,
        item_name_en;
END ;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;

--
-- Final view structure for view `epic_items_t2_view`
--

/*!50001 DROP VIEW IF EXISTS `epic_items_t2_view`*/;
/*!50001 SET @saved_cs_client          = @@character_set_client */;
/*!50001 SET @saved_cs_results         = @@character_set_results */;
/*!50001 SET @saved_col_connection     = @@collation_connection */;
/*!50001 SET character_set_client      = utf8mb4 */;
/*!50001 SET character_set_results     = utf8mb4 */;
/*!50001 SET collation_connection      = utf8mb4_unicode_ci */;
/*!50001 CREATE ALGORITHM=UNDEFINED */
/*!50013 DEFINER=`USER_discordbot`@`localhost` SQL SECURITY DEFINER */
/*!50001 VIEW `epic_items_t2_view` AS select `epic_items_t2`.`item_id` AS `item_id`,`epic_items_t2`.`item_type` AS `item_type`,`epic_items_t2`.`item_category` AS `item_category`,`epic_items_t2`.`item_name_en` AS `item_name_en`,`epic_items_t2`.`item_name_fr` AS `item_name_fr`,`epic_items_t2`.`item_name_es` AS `item_name_es`,`epic_items_t2`.`item_name_de` AS `item_name_de`,`epic_items_t2`.`item_url` AS `item_url`,`epic_items_t2`.`item_icon_url` AS `item_icon_url`,`epic_items_t2`.`created_at` AS `created_at`,`epic_items_t2`.`updated_at` AS `updated_at`,concat(`epic_items_t2`.`item_type`,' - ',`epic_items_t2`.`item_category`) AS `full_category`,case when `epic_items_t2`.`item_icon_url` is not null and `epic_items_t2`.`item_icon_url` <> '' then 1 else 0 end AS `has_icon` from `epic_items_t2` */;
/*!50001 SET character_set_client      = @saved_cs_client */;
/*!50001 SET character_set_results     = @saved_cs_results */;
/*!50001 SET collation_connection      = @saved_col_connection */;

--
-- Final view structure for view `guild_overview`
--

/*!50001 DROP VIEW IF EXISTS `guild_overview`*/;
/*!50001 SET @saved_cs_client          = @@character_set_client */;
/*!50001 SET @saved_cs_results         = @@character_set_results */;
/*!50001 SET @saved_col_connection     = @@collation_connection */;
/*!50001 SET character_set_client      = utf8mb4 */;
/*!50001 SET character_set_results     = utf8mb4 */;
/*!50001 SET collation_connection      = utf8mb4_unicode_ci */;
/*!50001 CREATE ALGORITHM=UNDEFINED */
/*!50013 DEFINER=`USER_discordbot`@`localhost` SQL SECURITY DEFINER */
/*!50001 VIEW `guild_overview` AS select `gs`.`guild_id` AS `guild_id`,`gs`.`guild_name` AS `guild_name`,`gs`.`guild_lang` AS `guild_lang`,`gs`.`guild_game` AS `guild_game`,`gs`.`guild_server` AS `guild_server`,`gs`.`initialized` AS `initialized`,`gs`.`premium` AS `premium`,`gs`.`created_at` AS `created_at`,count(distinct `gm`.`member_id`) AS `total_members`,count(distinct `sg`.`id`) AS `static_groups_count`,`gl`.`game_name` AS `game_name` from (((`guild_settings` `gs` left join `guild_members` `gm` on(`gs`.`guild_id` = `gm`.`guild_id`)) left join `guild_static_groups` `sg` on(`gs`.`guild_id` = `sg`.`guild_id` and `sg`.`is_active` = 1)) left join `games_list` `gl` on(`gs`.`guild_game` = `gl`.`id`)) group by `gs`.`guild_id`,`gs`.`guild_name`,`gs`.`guild_lang`,`gs`.`guild_game`,`gs`.`guild_server`,`gs`.`initialized`,`gs`.`premium`,`gs`.`created_at`,`gl`.`game_name` */;
/*!50001 SET character_set_client      = @saved_cs_client */;
/*!50001 SET character_set_results     = @saved_cs_results */;
/*!50001 SET collation_connection      = @saved_col_connection */;

--
-- Final view structure for view `loot_wishlist_stats`
--

/*!50001 DROP VIEW IF EXISTS `loot_wishlist_stats`*/;
/*!50001 SET @saved_cs_client          = @@character_set_client */;
/*!50001 SET @saved_cs_results         = @@character_set_results */;
/*!50001 SET @saved_col_connection     = @@collation_connection */;
/*!50001 SET character_set_client      = utf8mb4 */;
/*!50001 SET character_set_results     = utf8mb4 */;
/*!50001 SET collation_connection      = utf8mb4_unicode_ci */;
/*!50001 CREATE ALGORITHM=UNDEFINED */
/*!50013 DEFINER=`USER_discordbot`@`localhost` SQL SECURITY DEFINER */
/*!50001 VIEW `loot_wishlist_stats` AS select `loot_wishlist`.`guild_id` AS `guild_id`,`loot_wishlist`.`item_name` AS `item_name`,`loot_wishlist`.`item_id` AS `item_id`,count(0) AS `demand_count`,group_concat(distinct `loot_wishlist`.`user_id` order by `loot_wishlist`.`priority` DESC,`loot_wishlist`.`created_at` ASC separator ',') AS `interested_users`,avg(`loot_wishlist`.`priority`) AS `avg_priority`,min(`loot_wishlist`.`created_at`) AS `first_request`,max(`loot_wishlist`.`created_at`) AS `last_request` from `loot_wishlist` group by `loot_wishlist`.`guild_id`,`loot_wishlist`.`item_name`,`loot_wishlist`.`item_id` */;
/*!50001 SET character_set_client      = @saved_cs_client */;
/*!50001 SET character_set_results     = @saved_cs_results */;
/*!50001 SET collation_connection      = @saved_col_connection */;

--
-- Final view structure for view `member_statistics`
--

/*!50001 DROP VIEW IF EXISTS `member_statistics`*/;
/*!50001 SET @saved_cs_client          = @@character_set_client */;
/*!50001 SET @saved_cs_results         = @@character_set_results */;
/*!50001 SET @saved_col_connection     = @@collation_connection */;
/*!50001 SET character_set_client      = utf8mb4 */;
/*!50001 SET character_set_results     = utf8mb4 */;
/*!50001 SET collation_connection      = utf8mb4_unicode_ci */;
/*!50001 CREATE ALGORITHM=UNDEFINED */
/*!50013 DEFINER=`USER_discordbot`@`localhost` SQL SECURITY DEFINER */
/*!50001 VIEW `member_statistics` AS select `gm`.`guild_id` AS `guild_id`,`gm`.`member_id` AS `member_id`,`gm`.`username` AS `username`,`gm`.`class` AS `class`,`gm`.`GS` AS `GS`,`gm`.`DKP` AS `DKP`,`gm`.`nb_events` AS `nb_events`,`gm`.`registrations` AS `registrations`,`gm`.`attendances` AS `attendances`,case when `gm`.`registrations` > 0 then round(`gm`.`attendances` / `gm`.`registrations` * 100,2) else 0 end AS `attendance_rate`,case when `gm`.`nb_events` > 0 then round(`gm`.`DKP` / `gm`.`nb_events`,2) else 0 end AS `avg_dkp_per_event` from `guild_members` `gm` where `gm`.`username` is not null */;
/*!50001 SET character_set_client      = @saved_cs_client */;
/*!50001 SET character_set_results     = @saved_cs_results */;
/*!50001 SET collation_connection      = @saved_col_connection */;

--
-- Final view structure for view `static_groups_with_members`
--

/*!50001 DROP VIEW IF EXISTS `static_groups_with_members`*/;
/*!50001 SET @saved_cs_client          = @@character_set_client */;
/*!50001 SET @saved_cs_results         = @@character_set_results */;
/*!50001 SET @saved_col_connection     = @@collation_connection */;
/*!50001 SET character_set_client      = utf8mb4 */;
/*!50001 SET character_set_results     = utf8mb4 */;
/*!50001 SET collation_connection      = utf8mb4_unicode_ci */;
/*!50001 CREATE ALGORITHM=UNDEFINED */
/*!50013 DEFINER=`USER_discordbot`@`localhost` SQL SECURITY DEFINER */
/*!50001 VIEW `static_groups_with_members` AS select `sg`.`id` AS `group_id`,`sg`.`guild_id` AS `guild_id`,`sg`.`group_name` AS `group_name`,`sg`.`leader_id` AS `leader_id`,`sg`.`is_active` AS `is_active`,`sg`.`created_at` AS `group_created_at`,`sg`.`updated_at` AS `group_updated_at`,count(`sm`.`member_id`) AS `member_count`,group_concat(`sm`.`member_id` order by `sm`.`position_order` ASC separator ',') AS `member_ids`,group_concat(`sm`.`position_order` order by `sm`.`position_order` ASC separator ',') AS `member_positions` from (`guild_static_groups` `sg` left join `guild_static_members` `sm` on(`sg`.`id` = `sm`.`group_id`)) where `sg`.`is_active` = 1 group by `sg`.`id`,`sg`.`guild_id`,`sg`.`group_name`,`sg`.`leader_id`,`sg`.`is_active`,`sg`.`created_at`,`sg`.`updated_at` */;
/*!50001 SET character_set_client      = @saved_cs_client */;
/*!50001 SET character_set_results     = @saved_cs_results */;
/*!50001 SET collation_connection      = @saved_col_connection */;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2025-08-20 20:44:55
