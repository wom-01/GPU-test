<?php

namespace App\Core\Controller\Panel;

use App\Core\Controller\AbstractController;
use App\Core\Enum\PermissionEnum;
use App\Core\Service\DockerGpuManageClient;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\HttpFoundation\Response;
use Symfony\Component\Routing\Annotation\Route;

class ComputeNodeController extends AbstractController
{
    public function __construct(private readonly DockerGpuManageClient $dockerGpuManageClient) {}

    #[Route('/panel/compute-nodes', name: 'admin_compute_nodes', methods: ['GET'])]
    public function index(): Response
    {
        $this->denyAccessUnlessGranted(PermissionEnum::ACCESS_SERVERS->value);

        $nodes = [];
        $connectionError = null;
        try {
            $nodes = $this->dockerGpuManageClient->getManagedNodes();
        } catch (\Throwable $exception) {
            $connectionError = $exception->getMessage();
        }

        return $this->render('panel/admin/compute_nodes/index.html.twig', [
            'nodes' => $nodes,
            'connectionError' => $connectionError,
        ]);
    }

    #[Route('/panel/compute-nodes/new', name: 'admin_compute_node_new', methods: ['GET', 'POST'])]
    public function create(Request $request): Response
    {
        $this->denyAccessUnlessGranted(PermissionEnum::CREATE_SERVER->value);

        $node = $this->emptyNode();
        if ($request->isMethod('POST')) {
            $this->validateFormToken($request, 'compute_node_create');
            $node = array_replace($node, $this->nodePayload($request));

            try {
                $this->dockerGpuManageClient->createManagedNode($node);
                $this->addFlash('success', '算力节点已添加。');

                return $this->redirectToRoute('admin_compute_nodes');
            } catch (\Throwable $exception) {
                $this->addFlash('danger', $exception->getMessage());
            }
        }

        return $this->render('panel/admin/compute_nodes/form.html.twig', [
            'node' => $node,
            'isEdit' => false,
        ]);
    }

    #[Route('/panel/compute-nodes/{id}/edit', name: 'admin_compute_node_edit', requirements: ['id' => '\d+'], methods: ['GET', 'POST'])]
    public function edit(int $id, Request $request): Response
    {
        $this->denyAccessUnlessGranted(PermissionEnum::EDIT_SERVER->value);

        try {
            $node = $this->dockerGpuManageClient->getManagedNode($id);
        } catch (\Throwable $exception) {
            throw $this->createNotFoundException('算力节点不存在', $exception);
        }

        if ($request->isMethod('POST')) {
            $this->validateFormToken($request, 'compute_node_edit_' . $id);
            $node = array_replace($node, $this->nodePayload($request));

            try {
                $this->dockerGpuManageClient->updateManagedNode($id, $node);
                $this->addFlash('success', '算力节点已更新。');

                return $this->redirectToRoute('admin_compute_nodes');
            } catch (\Throwable $exception) {
                $this->addFlash('danger', $exception->getMessage());
            }
        }

        return $this->render('panel/admin/compute_nodes/form.html.twig', [
            'node' => $node,
            'isEdit' => true,
        ]);
    }

    #[Route('/panel/compute-nodes/{id}/shelf', name: 'admin_compute_node_shelf', requirements: ['id' => '\d+'], methods: ['POST'])]
    public function shelf(int $id, Request $request): Response
    {
        $this->denyAccessUnlessGranted(PermissionEnum::EDIT_SERVER->value);
        $this->validateFormToken($request, 'compute_node_shelf_' . $id);

        try {
            $isOnShelf = $request->request->getBoolean('isOnShelf');
            $this->dockerGpuManageClient->setManagedNodeShelf($id, $isOnShelf);
            $this->addFlash('success', $isOnShelf ? '节点已上架。' : '节点已下架。');
        } catch (\Throwable $exception) {
            $this->addFlash('danger', $exception->getMessage());
        }

        return $this->redirectToRoute('admin_compute_nodes');
    }

    #[Route('/panel/compute-nodes/{id}/delete', name: 'admin_compute_node_delete', requirements: ['id' => '\d+'], methods: ['POST'])]
    public function delete(int $id, Request $request): Response
    {
        $this->denyAccessUnlessGranted(PermissionEnum::DELETE_SERVER->value);
        $this->validateFormToken($request, 'compute_node_delete_' . $id);

        try {
            $this->dockerGpuManageClient->deleteManagedNode($id);
            $this->addFlash('success', '算力节点已删除。');
        } catch (\Throwable $exception) {
            $this->addFlash('danger', $exception->getMessage());
        }

        return $this->redirectToRoute('admin_compute_nodes');
    }

    private function validateFormToken(Request $request, string $tokenId): void
    {
        if (!$this->isCsrfTokenValid($tokenId, (string) $request->request->get('_token'))) {
            throw $this->createAccessDeniedException('Invalid CSRF token.');
        }
    }

    /** @return array<string, mixed> */
    private function nodePayload(Request $request): array
    {
        $payload = [];
        foreach ([
            'name', 'region', 'publicIp', 'privateIp', 'username', 'password', 'gpuName',
            'dockerAddress', 'caCert', 'clientCert', 'clientKey', 'remark', 'hamiCore',
        ] as $field) {
            $payload[$field] = trim((string) $request->request->get($field, ''));
        }

        foreach (['cpu', 'memory', 'systemDisk', 'dataDisk', 'gpuCount', 'memoryCapacity'] as $field) {
            $payload[$field] = max(0, (int) $request->request->get($field, 0));
        }

        $payload['sshPort'] = min(65535, max(1, (int) $request->request->get('sshPort', 22)));
        $payload['useTls'] = $request->request->getBoolean('useTls');
        $payload['isOnShelf'] = $request->request->getBoolean('isOnShelf');

        return $payload;
    }

    /** @return array<string, mixed> */
    private function emptyNode(): array
    {
        return [
            'name' => '',
            'region' => '',
            'cpu' => 0,
            'memory' => 0,
            'systemDisk' => 0,
            'dataDisk' => 0,
            'publicIp' => '',
            'privateIp' => '',
            'sshPort' => 22,
            'username' => '',
            'gpuName' => '',
            'gpuCount' => 0,
            'memoryCapacity' => 0,
            'dockerAddress' => '',
            'useTls' => true,
            'isOnShelf' => true,
            'remark' => '',
            'hamiCore' => '',
            'passwordConfigured' => false,
            'caCertConfigured' => false,
            'clientCertConfigured' => false,
            'clientKeyConfigured' => false,
        ];
    }
}
