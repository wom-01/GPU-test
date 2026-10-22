<?php

namespace App\Core\EventSubscriber\Kernel;

use App\Core\Enum\SettingEnum;
use App\Core\Service\SettingService;
use Symfony\Component\HttpKernel\KernelEvents;
use Symfony\Component\HttpKernel\Event\RequestEvent;
use Symfony\Component\EventDispatcher\EventSubscriberInterface;

readonly class LocaleSubscriber implements EventSubscriberInterface
{
    public function __construct(
        private SettingService $settingService,
    ) {}

    public function onKernelRequest(RequestEvent $event): void
    {
        $request = $event->getRequest();
        $localeSetting = $this->settingService->getSetting(SettingEnum::LOCALE->value);

        if ($localeSetting) {
            // "cn" is the project's Chinese catalogue name, but ICU requires a valid locale.
            $request->setLocale($localeSetting === 'cn' ? 'zh_CN' : $localeSetting);
        }
    }

    public static function getSubscribedEvents(): array
    {
        return [
            KernelEvents::REQUEST => [['onKernelRequest', 20]],
        ];
    }
}
