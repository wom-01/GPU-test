<?php

namespace App\Core\Provider\Payment;

use App\Core\DTO\PaymentSessionDTO;
use App\Core\Enum\PaymentStatusEnum;
use App\Core\Enum\SettingEnum;
use App\Core\Service\SettingService;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Contracts\HttpClient\HttpClientInterface;

abstract class EpayProviderBase implements PaymentProviderInterface
{
    public function __construct(
        private readonly SettingService $settingService,
        private readonly HttpClientInterface $httpClient,
    ) {}

    abstract protected function getPaymentType(): string;

    public function createSession(float $amount, string $currency, string $successUrl, string $cancelUrl): ?PaymentSessionDTO
    {
        if (!$this->isConfigured() || strtoupper($currency) !== 'CNY') {
            return null;
        }

        $orderNumber = sprintf('RC%s%s', date('YmdHis'), bin2hex(random_bytes(4)));
        $parameters = [
            'pid' => $this->getPid(),
            'type' => $this->getPaymentType(),
            'out_trade_no' => $orderNumber,
            'notify_url' => $this->buildNotifyUrl($successUrl),
            'return_url' => $successUrl,
            'name' => 'GPU 算力账户充值',
            'money' => number_format($amount, 2, '.', ''),
            'sign_type' => 'MD5',
        ];
        $parameters['sign'] = $this->sign($parameters);

        return new PaymentSessionDTO(
            $orderNumber,
            $amount,
            'CNY',
            PaymentStatusEnum::UNPAID->value,
            $this->getBaseUrl() . '/submit.php?' . http_build_query($parameters),
        );
    }

    public function retrieveSession(string $sessionId): ?PaymentSessionDTO
    {
        if (!$this->isConfigured()) {
            return null;
        }

        try {
            $response = $this->httpClient->request('GET', $this->getBaseUrl() . '/api.php', [
                'query' => [
                    'act' => 'order',
                    'pid' => $this->getPid(),
                    'key' => $this->getKey(),
                    'out_trade_no' => $sessionId,
                ],
                'timeout' => 15,
            ])->toArray(false);
        } catch (\Throwable) {
            return null;
        }

        if ((int) ($response['code'] ?? 0) !== 1) {
            return null;
        }

        $paid = (int) ($response['status'] ?? 0) === 1;
        $amount = (float) ($response['money'] ?? 0);

        return new PaymentSessionDTO(
            $sessionId,
            $amount,
            'CNY',
            $paid ? PaymentStatusEnum::PAID->value : PaymentStatusEnum::UNPAID->value,
            $paid ? null : $this->getBaseUrl(),
        );
    }

    public function isConfigured(): bool
    {
        return $this->getBaseUrl() !== '' && $this->getPid() !== '' && $this->getKey() !== '';
    }

    public function getSupportedCurrencies(): array
    {
        return ['CNY'];
    }

    public function getSuccessCallbackRoute(): string
    {
        return 'payment_callback_success';
    }

    public function getCancelCallbackRoute(): string
    {
        return 'payment_callback_cancel';
    }

    public function extractSessionIdFromCallback(Request $request): ?string
    {
        return $request->query->get('out_trade_no');
    }

    public function buildSuccessUrl(string $baseUrl): string
    {
        return $baseUrl;
    }

    public function buildCancelUrl(string $baseUrl): string
    {
        return $baseUrl;
    }

    public function verifyNotification(array $parameters): bool
    {
        $receivedSign = (string) ($parameters['sign'] ?? '');
        return $receivedSign !== ''
            && strtoupper((string) ($parameters['sign_type'] ?? 'MD5')) === 'MD5'
            && hash_equals($this->sign($parameters), $receivedSign)
            && ($parameters['pid'] ?? '') === $this->getPid()
            && ($parameters['trade_status'] ?? '') === 'TRADE_SUCCESS';
    }

    private function sign(array $parameters): string
    {
        unset($parameters['sign'], $parameters['sign_type']);
        $parameters = array_filter($parameters, static fn ($value) => $value !== '' && $value !== null);
        ksort($parameters);
        $parts = [];
        foreach ($parameters as $key => $value) {
            $parts[] = $key . '=' . $value;
        }

        return md5(implode('&', $parts) . $this->getKey());
    }

    private function buildNotifyUrl(string $successUrl): string
    {
        $parts = parse_url($successUrl);
        if (!isset($parts['scheme'], $parts['host'])) {
            return $successUrl;
        }
        $port = isset($parts['port']) ? ':' . $parts['port'] : '';
        return sprintf('%s://%s%s/payment/epay/notify', $parts['scheme'], $parts['host'], $port);
    }

    private function getBaseUrl(): string
    {
        return rtrim((string) $this->settingService->getSetting(SettingEnum::EPAY_URL->value), '/');
    }

    private function getPid(): string
    {
        return trim((string) $this->settingService->getSetting(SettingEnum::EPAY_PID->value));
    }

    private function getKey(): string
    {
        return trim((string) $this->settingService->getSetting(SettingEnum::EPAY_KEY->value));
    }
}
