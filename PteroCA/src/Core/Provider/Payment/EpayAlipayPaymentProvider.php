<?php

namespace App\Core\Provider\Payment;

class EpayAlipayPaymentProvider extends EpayProviderBase
{
    protected function getPaymentType(): string { return 'alipay'; }
    public function getIdentifier(): string { return 'epay_alipay'; }
    public function getDisplayName(): string { return '支付宝'; }
    public function getIcon(): string { return 'fab fa-alipay'; }
    public function getDescription(): string { return '使用支付宝扫码或跳转支付'; }
    public function getMetadata(): array { return ['color' => '#1677ff', 'supports_recurring' => false]; }
}
