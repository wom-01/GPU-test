<?php

namespace App\Core\Controller\Panel\Setting;

use App\Core\Controller\API\APIAbstractController;
use App\Core\Enum\PermissionEnum;
use App\Core\Service\Marketplace\MarketplaceService;
use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\Routing\Attribute\Route;
use Throwable;

class MarketplaceProxyController extends APIAbstractController
{
    public function __construct(
        private readonly MarketplaceService $marketplaceService,
    ) {}

    #[Route('/panel/marketplace-api/products', name: 'panel_marketplace_products', methods: ['GET'])]
    public function products(Request $request): JsonResponse
    {
        $this->requirePermission(PermissionEnum::ACCESS_PLUGINS);

        try {
            $data = $this->marketplaceService->getProducts(
                page:  (int)    $request->query->get('page',  1),
                limit: (int)    $request->query->get('limit', 10),
                sort:  (string) $request->query->get('sort',  'newest'),
                tags:  (string) $request->query->get('tags',  ''),
            );
        } catch (Throwable) {
            return new JsonResponse([
                'error' => '插件市场暂时无法连接，请稍后重试。',
                'data' => [],
            ], JsonResponse::HTTP_SERVICE_UNAVAILABLE);
        }

        return new JsonResponse($data);
    }
}
