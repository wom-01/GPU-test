<?php

declare(strict_types=1);

namespace DoctrineMigrations;

use Doctrine\DBAL\Schema\Schema;
use Doctrine\Migrations\AbstractMigration;

final class Version20260724150000 extends AbstractMigration
{
    public function getDescription(): string
    {
        return 'Add day, month and year GPU rental price plans based on hourly prices';
    }

    public function up(Schema $schema): void
    {
        foreach ([
            'days' => [1, 24],
            'months' => [1, 720],
            'years' => [1, 8760],
        ] as $unit => [$value, $multiplier]) {
            $this->addSql(sprintf(
                "INSERT INTO product_price (product_id, type, value, unit, price, deleted_at) SELECT base.product_id, 'static', %d, '%s', ROUND(base.price * %d, 2), NULL FROM product_price base WHERE base.type = 'static' AND base.unit = 'hours' AND base.value = 1 AND base.deleted_at IS NULL AND NOT EXISTS (SELECT 1 FROM product_price existing WHERE existing.product_id = base.product_id AND existing.type = 'static' AND existing.unit = '%s' AND existing.value = %d AND existing.deleted_at IS NULL)",
                $value,
                $unit,
                $multiplier,
                $unit,
                $value,
            ));
        }
    }

    public function down(Schema $schema): void
    {
        $this->addSql("DELETE FROM product_price WHERE type = 'static' AND value = 1 AND unit IN ('days', 'months', 'years')");
    }
}
