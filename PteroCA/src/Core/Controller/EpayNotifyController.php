<?php

namespace App\Core\Controller;

use App\Core\Provider\Payment\EpayProviderBase;
use App\Core\Service\Payment\PaymentGatewayManager;
use App\Core\Service\Payment\PaymentService;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\HttpFoundation\Response;
use Symfony\Component\Routing\Annotation\Route;

class EpayNotifyController
{
    public function __construct(
        private readonly PaymentGatewayManager $gatewayManager,
        private readonly PaymentService $paymentService,
    ) {}

    #[Route('/payment/epay/notify', name: 'epay_notify', methods: ['GET', 'POST'])]
    public function notify(Request $request): Response
    {
        $parameters = array_merge($request->query->all(), $request->request->all());
        $identifier = ($parameters['type'] ?? '') === 'wxpay' ? 'epay_wechat' : 'epay_alipay';
        $provider = $this->gatewayManager->getProvider($identifier);

        if (!$provider instanceof EpayProviderBase || !$provider->verifyNotification($parameters)) {
            return new Response('fail', Response::HTTP_BAD_REQUEST);
        }

        $sessionId = (string) ($parameters['out_trade_no'] ?? '');
        if ($sessionId === '' || $this->paymentService->finalizePaymentBySessionId($sessionId) !== null) {
            return new Response('fail', Response::HTTP_BAD_REQUEST);
        }

        return new Response('success');
    }
}
