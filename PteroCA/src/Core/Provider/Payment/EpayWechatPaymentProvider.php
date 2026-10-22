<?php

namespace App\Core\Provider\Payment;

class EpayWechatPaymentProvider extends EpayProviderBase
{
    protected function getPaymentType(): string { return 'wxpay'; }
    public function getIdentifier(): string { return 'epay_wechat'; }
    public function getDisplayName(): string { return '微信支付'; }
    public function getIcon(): string { return 'fab fa-weixin'; }
    public function getDescription(): string { return '使用微信扫码完成支付'; }
    public function getMetadata(): array { return ['color' => '#07c160', 'supports_recurring' => false]; }
}
