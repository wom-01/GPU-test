<?php

namespace App\Core\Service\Identity;

use App\Core\Enum\SettingEnum;
use App\Core\Service\SettingService;

class AliyunRealNameService
{
    public function __construct(private readonly SettingService $settingService)
    {
    }

    public function isEnabled(): bool
    {
        return $this->settingService->getSetting(SettingEnum::ALIYUN_REAL_NAME_ENABLED->value) === '1';
    }

    public function isConfigured(): bool
    {
        foreach ([
            SettingEnum::ALIYUN_CLOUDAUTH_ACCESS_KEY_ID,
            SettingEnum::ALIYUN_CLOUDAUTH_ACCESS_KEY_SECRET,
            SettingEnum::ALIYUN_CLOUDAUTH_SCENE_ID,
        ] as $setting) {
            if (empty($this->settingService->getSetting($setting->value))) {
                return false;
            }
        }

        return true;
    }

    public function start(string $name, string $idNumber, int $userId): array
    {
        if (!$this->isConfigured()) {
            throw new \RuntimeException('实名认证服务尚未配置，请联系管理员。');
        }

        // The provider adapter is activated after the RAM credentials and SceneId are supplied.
        throw new \RuntimeException('阿里云认证参数已预留，接口凭证提交后即可启用。');
    }
}
