<?php

namespace App\Core\Service\Server;

use App\Core\Entity\Server;
use App\Core\Service\DockerGpuManageClient;
use App\Core\Service\Logs\ServerLogService;
use App\Core\Service\Pterodactyl\PterodactylApplicationService;
use Exception;
use Psr\Log\LoggerInterface;

readonly class DeleteServerService
{
    public function __construct(
        private PterodactylApplicationService $pterodactylApplicationService,
        private DockerGpuManageClient         $dockerGpuManageClient,
        private ServerLogService              $serverLogService,
        private LoggerInterface               $logger,
    )
    {
    }

    public function deleteServer(Server $entityInstance): void
    {
        try {
            if ($this->dockerGpuManageClient->isGpuOrderIdentifier(
                $entityInstance->getPterodactylServerIdentifier()
            )) {
                $this->dockerGpuManageClient->applyAction(
                    $entityInstance->getPterodactylServerId(),
                    'terminate'
                );
            } else {
                $this->pterodactylApplicationService
                    ->getApplicationApi()
                    ->servers()
                    ->deleteServer($entityInstance->getPterodactylServerId());
            }
        } catch (Exception $e) {
            $this->logger->error('Failed to delete remote server while deleting local entity', [
                'exception' => $e,
                'serverId' => $entityInstance->getPterodactylServerId(),
                'entityId' => $entityInstance->getId(),
            ]);
        }

        $this->serverLogService->deleteServerActionLogs($entityInstance);
    }
}
