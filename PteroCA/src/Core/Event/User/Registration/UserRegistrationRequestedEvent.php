<?php

namespace App\Core\Event\User\Registration;

use App\Core\Event\AbstractDomainEvent;
use App\Core\Event\StoppableEventTrait;

class UserRegistrationRequestedEvent extends AbstractDomainEvent
{
    use StoppableEventTrait;

    public function __construct(
        private readonly string $email,
        private readonly array $context = [], // ip, userAgent, locale, source, referralCode, consents
        private readonly ?string $eventId = null,
    ) {
        parent::__construct($eventId);
    }

    public function getEmail(): string
    {
        return $this->email;
    }

    public function getContext(): array
    {
        return $this->context;
    }

    public function getIp(): ?string
    {
        return $this->context['ip'] ?? null;
    }

    public function getUserAgent(): ?string
    {
        return $this->context['userAgent'] ?? null;
    }

    public function getLocale(): ?string
    {
        return $this->context['locale'] ?? null;
    }

    public function getSource(): ?string
    {
        return $this->context['source'] ?? null;
    }
}
