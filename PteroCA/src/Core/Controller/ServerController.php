<?php

namespace App\Core\Controller;

use App\Core\Entity\Server;
use App\Core\Enum\PermissionEnum;
use App\Core\Enum\ViewNameEnum;
use App\Core\Event\Server\ServerManagementDataLoadedEvent;
use App\Core\Event\Server\ServerManagementPageAccessedEvent;
use App\Core\Event\Server\ServersListAccessedEvent;
use App\Core\Event\Server\ServersListDataLoadedEvent;
use App\Core\Event\Server\Tab\ServerTabsCollectedEvent;
use App\Core\DTO\ServerTabContext;
use App\Core\Repository\ServerRepository;
use App\Core\Service\Pterodactyl\PterodactylRedirectService;
use App\Core\Service\Tab\ServerTabRegistry;
use App\Core\Service\Server\ServerDataService;
use App\Core\Service\Server\DeleteServerService;
use App\Core\Service\Server\ServerService;
use App\Core\Service\DockerGpuManageClient;
use Exception;
use Psr\Log\LoggerInterface;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\HttpFoundation\Response;
use App\Core\Enum\WidgetContext;
use App\Core\Service\Widget\WidgetRegistry;
use App\Core\Event\Widget\WidgetsCollectedEvent;
use Symfony\Component\Routing\Annotation\Route;
use Symfony\Contracts\Translation\TranslatorInterface;

class ServerController extends AbstractController
{
    #[Route('/servers', name: 'servers')]
    public function servers(
        Request $request,
        ServerService $serverService,
    ): Response
    {
        if ($request->attributes->get('_route') === 'servers') {
            return $this->redirectToRoute('panel', ['routeName' => 'servers']);
        }

        $this->checkPermission(PermissionEnum::ACCESS_MY_SERVERS);

        $this->dispatchSimpleEvent(ServersListAccessedEvent::class, $request);

        $imagePath = $this->getParameter('products_base_path') . '/';
        $servers = array_map(function (Server $server) use ($imagePath) {
            if (!empty($server->getServerProduct()?->getOriginalProduct()?->getImagePath())) {
                $server->setImagePath($imagePath . $server->getServerProduct()?->getOriginalProduct()?->getImagePath());
            }
            return $server;
        }, $serverService->getServersWithAccess($this->getUser()));

        $this->dispatchDataEvent(
            ServersListDataLoadedEvent::class,
            $request,
            [$servers, count($servers)]
        );

        $viewData = [
            'servers' => $servers,
        ];

        $widgetRegistry = new WidgetRegistry();
        $contextData = ['user' => $this->getUser()];
        $this->dispatchEvent(new WidgetsCollectedEvent($widgetRegistry, WidgetContext::SERVER_LIST, $contextData));
        $viewData = array_merge($viewData, compact('widgetRegistry', 'contextData') + ['widgetContext' => WidgetContext::SERVER_LIST]);

        return $this->renderWithEvent(ViewNameEnum::SERVERS_LIST, 'panel/servers/servers.html.twig', $viewData, $request);
    }

    #[Route(
        '/panel/servers/{id}/delete',
        name: 'panel_server_delete',
        requirements: ['id' => '\\d+'],
        methods: ['POST']
    )]
    public function deleteServer(
        int $id,
        Request $request,
        ServerRepository $serverRepository,
        DeleteServerService $deleteServerService,
        TranslatorInterface $translator,
        LoggerInterface $logger,
    ): Response
    {
        $this->checkPermission(PermissionEnum::ACCESS_MY_SERVERS);

        $server = $serverRepository->find($id);
        if ($server === null || $server->getDeletedAt() !== null) {
            throw $this->createNotFoundException();
        }

        if ($server->getUser()->getId() !== $this->getUserId()) {
            throw $this->createAccessDeniedException();
        }

        if (!$this->isCsrfTokenValid(
            'server_delete_' . $server->getId(),
            (string) $request->request->get('_token')
        )) {
            throw $this->createAccessDeniedException('Invalid CSRF token.');
        }

        if (!$server->getIsSuspended() && $server->getExpiresAt() > new \DateTime()) {
            $this->addFlash('danger', $translator->trans('pteroca.servers.delete_not_allowed'));

            return $this->redirectToRoute('panel', ['routeName' => 'servers']);
        }

        try {
            $deleteServerService->deleteServer($server);
            $server->setDeletedAtValue();
            $serverRepository->save($server);
            $this->addFlash('success', $translator->trans('pteroca.servers.delete_success'));
        } catch (\Throwable $exception) {
            $logger->error('User failed to delete server', [
                'server_id' => $server->getId(),
                'user_id' => $this->getUserId(),
                'error' => $exception->getMessage(),
            ]);
            $this->addFlash('danger', $translator->trans('pteroca.servers.delete_failed'));
        }

        return $this->redirectToRoute('panel', ['routeName' => 'servers']);
    }

    #[Route('/server', name: 'server')]
    public function server(
        Request $request,
        ServerRepository $serverRepository,
        ServerDataService $serverDataService,
        ServerTabRegistry $serverTabRegistry,
        PterodactylRedirectService $pterodactylRedirectService,
        LoggerInterface $logger,
        DockerGpuManageClient $dockerGpuManageClient,
    ): Response
    {
        if ($request->attributes->get('_route') === 'server') {
            return $this->redirectToRoute('panel', array_filter([
                'routeName' => 'server',
                'id' => $request->query->get('id'),
                'page' => $request->query->get('page'),
            ]));
        }

        $this->checkPermission();

        $serverId = $request->get('id');
        if (empty($serverId)) {
            throw $this->createNotFoundException();
        }

        if ($pterodactylRedirectService->shouldUsePterodactylPanel()) {
            return $pterodactylRedirectService->createServerRedirect($serverId);
        }

        $currentPage = $request->get('page', 1);

        /** @var ?Server $server */
        $server = current($serverRepository->findBy(['pterodactylServerIdentifier' => $serverId]));
        if (empty($server) || !empty($server->getDeletedAt())) {
            throw $this->createNotFoundException();
        }

        if ($server->getUser() !== $this->getUser()
            && !$this->isGranted(PermissionEnum::ACCESS_SERVERS->value)) {
            throw $this->createAccessDeniedException();
        }

        if ($dockerGpuManageClient->isGpuOrderIdentifier($server->getPterodactylServerIdentifier())) {
            try {
                $order = $dockerGpuManageClient->getOrder($server->getPterodactylServerId());
                if ($order === []) {
                    throw new \RuntimeException('GPU order was not found');
                }
            } catch (\Throwable $exception) {
                $logger->warning('Failed to load GPU rental order', [
                    'server_id' => $server->getId(),
                    'remote_order_id' => $server->getPterodactylServerId(),
                    'error' => $exception->getMessage(),
                ]);
                $order = [
                    'orderNo' => $server->getPterodactylServerIdentifier(),
                    'status' => 'unknown',
                    'provisionError' => '订单记录暂时无法读取，请联系平台客服。',
                ];
            }
            return $this->render('panel/server/gpu_server.html.twig', [
                'server' => $server,
                'order' => $order,
            ]);
        }

        $this->dispatchDataEvent(
            ServerManagementPageAccessedEvent::class,
            $request,
            [
                $server->getId(),
                $server->getPterodactylServerIdentifier(),
                $server->getServerProduct()->getName(),
                $server->getUser() === $this->getUser(), // isOwner
                $this->isGranted(PermissionEnum::ACCESS_SERVERS->value), // isAdminView
            ]
        );

        try {
            $serverData = $serverDataService->getServerData($server, $this->getUser(), $currentPage);
        } catch (Exception $exception) {
            $logger->error('Failed to load server data from Pterodactyl', [
                'server_id' => $server->getId(),
                'pterodactyl_server_identifier' => $server->getPterodactylServerIdentifier(),
                'error' => $exception->getMessage(),
            ]);
            return $this->renderWithEvent(
                ViewNameEnum::SERVER_MANAGEMENT,
                'panel/server/server.html.twig',
                [
                    'server' => $server,
                    'serverData' => null,
                    'connectionError' => true,
                ],
                $request
            );
        }

        $isAdminView = $this->isGranted(PermissionEnum::ACCESS_SERVERS->value);
        $isOwner = $server->getUser() === $this->getUser();

        $loadedDataSections = [];
        if (!empty($serverData->pterodactylServer)) $loadedDataSections[] = 'pterodactyl_server';
        if (!empty($serverData->allocatedPorts)) $loadedDataSections[] = 'allocations';
        if (!empty($serverData->serverBackups)) $loadedDataSections[] = 'backups';
        if (!empty($serverData->subusers)) $loadedDataSections[] = 'subusers';
        if (!empty($serverData->activityLogs)) $loadedDataSections[] = 'activity_logs';
        if (!empty($serverData->serverSchedules)) $loadedDataSections[] = 'schedules';
        if (!empty($serverData->serverDetails)) $loadedDataSections[] = 'server_details';
        if (!empty($serverData->serverVariables)) $loadedDataSections[] = 'server_variables';
        if (!empty($serverData->dockerImages)) $loadedDataSections[] = 'docker_images';
        if (!empty($serverData->availableNestEggs)) $loadedDataSections[] = 'available_nest_eggs';

        $this->dispatchDataEvent(
            ServerManagementDataLoadedEvent::class,
            $request,
            [
                $server->getId(),
                $server->getPterodactylServerIdentifier(),
                $serverData->isInstalling,
                $serverData->isSuspended ?? false,
                !empty($serverData->serverPermissions?->toArray()),
                $loadedDataSections,
            ]
        );

        if (!$serverData->isInstalling && empty($serverData->serverPermissions?->toArray()) && !$isAdminView) {
            throw $this->createAccessDeniedException();
        }

        $tabContext = new ServerTabContext(
            server: $server,
            serverData: $serverData,
            user: $this->getUser(),
            isAdminView: $isAdminView,
            isOwner: $isOwner,
        );

        $context = $this->buildMinimalEventContext($request);
        $tabsEvent = new ServerTabsCollectedEvent($serverTabRegistry, $tabContext, $context);
        $this->dispatchEvent($tabsEvent);

        $visibleTabs = $serverTabRegistry->getVisibleTabs($tabContext);
        $tabAssets = $serverTabRegistry->getTabAssets($visibleTabs);

        $widgetRegistry = new WidgetRegistry();
        $contextData = ['user' => $this->getUser(), 'server' => $server];
        $this->dispatchEvent(new WidgetsCollectedEvent($widgetRegistry, WidgetContext::SERVER_DETAIL, $contextData));

        return $this->renderWithEvent(
            ViewNameEnum::SERVER_MANAGEMENT,
            'panel/server/server.html.twig',
            [
                'server' => $server,
                'serverData' => $serverData,
                'isAdminView' => $isAdminView,
                'isOwner' => $isOwner,
                'tabRegistry' => $serverTabRegistry,
                'tabContext' => $tabContext,
                'visibleTabs' => $visibleTabs,
                'tabAssets' => $tabAssets,
                'widgetRegistry' => $widgetRegistry,
                'widgetContext' => WidgetContext::SERVER_DETAIL,
                'contextData' => $contextData,
            ],
            $request
        );
    }
}
