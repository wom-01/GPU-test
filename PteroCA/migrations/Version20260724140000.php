<?php

declare(strict_types=1);

namespace DoctrineMigrations;

use Doctrine\DBAL\Schema\Schema;
use Doctrine\Migrations\AbstractMigration;

final class Version20260724140000 extends AbstractMigration
{
    public function getDescription(): string
    {
        return 'Add Aliyun real-name verification settings and user status';
    }

    public function up(Schema $schema): void
    {
        $this->addSql("ALTER TABLE `user` ADD real_name_status VARCHAR(20) NOT NULL DEFAULT 'unverified', ADD real_name_certify_id VARCHAR(128) DEFAULT NULL, ADD real_name_verified_at DATETIME DEFAULT NULL");
        $this->addSql("INSERT INTO setting (name, value, type, context, hierarchy, nullable) SELECT 'aliyun_real_name_enabled', '0', 'boolean', 'security_settings', 70, 0 WHERE NOT EXISTS (SELECT 1 FROM setting WHERE name = 'aliyun_real_name_enabled')");
        $this->addSql("INSERT INTO setting (name, value, type, context, hierarchy, nullable) SELECT 'aliyun_cloudauth_access_key_id', NULL, 'secret', 'security_settings', 71, 1 WHERE NOT EXISTS (SELECT 1 FROM setting WHERE name = 'aliyun_cloudauth_access_key_id')");
        $this->addSql("INSERT INTO setting (name, value, type, context, hierarchy, nullable) SELECT 'aliyun_cloudauth_access_key_secret', NULL, 'secret', 'security_settings', 72, 1 WHERE NOT EXISTS (SELECT 1 FROM setting WHERE name = 'aliyun_cloudauth_access_key_secret')");
        $this->addSql("INSERT INTO setting (name, value, type, context, hierarchy, nullable) SELECT 'aliyun_cloudauth_scene_id', NULL, 'text', 'security_settings', 73, 1 WHERE NOT EXISTS (SELECT 1 FROM setting WHERE name = 'aliyun_cloudauth_scene_id')");
    }

    public function down(Schema $schema): void
    {
        $this->addSql("DELETE FROM setting WHERE name IN ('aliyun_real_name_enabled', 'aliyun_cloudauth_access_key_id', 'aliyun_cloudauth_access_key_secret', 'aliyun_cloudauth_scene_id')");
        $this->addSql('ALTER TABLE `user` DROP real_name_status, DROP real_name_certify_id, DROP real_name_verified_at');
    }
}
