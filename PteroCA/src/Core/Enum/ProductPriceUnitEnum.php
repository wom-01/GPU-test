<?php

namespace App\Core\Enum;

enum ProductPriceUnitEnum: string
{
    case DAYS = 'days';
    case HOURS = 'hours';
    case MINUTES = 'minutes';
    case MONTHS = 'months';
    case YEARS = 'years';

    public static function getChoices(): array
    {
        return [
            'pteroca.crud.product.days' => self::DAYS,
            'pteroca.crud.product.hours' => self::HOURS,
            'pteroca.crud.product.minutes' => self::MINUTES,
            'pteroca.crud.product.months' => self::MONTHS,
            'pteroca.crud.product.years' => self::YEARS,
        ];
    }
}
