<?php

namespace App\Core\Controller\API;

use App\Core\Enum\PermissionEnum;
use App\Core\Service\Server\ServerEggService;
use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\Routing\Annotation\Route;

class EggsController extends APIAbstractController
{
    public function __construct(
        private readonly ServerEggService $serverEggService,
    ) {}

    #[Route('/panel/api/get-eggs/{nestId}', name: 'api_get_eggs', methods: ['GET'])]
    public function getEggs(int $nestId): JsonResponse
    {
        $this->requirePermission(PermissionEnum::EDIT_PRODUCT);

        if (!empty($_ENV['DGM_API_URL'] ?? getenv('DGM_API_URL'))) {
            return new JsonResponse([
                'choices' => ['GPU 计算环境' => 1],
                'eggs' => [
                    1 => [
                        'id' => 1,
                        'name' => 'GPU 计算环境',
                        'startup' => '',
                        'docker_image' => '',
                        'docker_images' => [],
                        'relationships' => ['variables' => []],
                    ],
                ],
                'translations' => [],
            ]);
        }

        return new JsonResponse($this->serverEggService->prepareEggsDataByNest($nestId));
    }
}
