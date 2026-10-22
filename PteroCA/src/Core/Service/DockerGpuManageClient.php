<?php

namespace App\Core\Service;

use RuntimeException;
use Symfony\Contracts\HttpClient\HttpClientInterface;

readonly class DockerGpuManageClient
{
    public function __construct(private HttpClientInterface $httpClient) {}

    public function isEnabled(): bool
    {
        return $this->baseUrl() !== '' && $this->apiKey() !== '';
    }

    public function isTestOrderModeEnabled(): bool
    {
        $value = $_ENV['DGM_ALLOW_EMPTY_GPU_ORDERS'] ?? getenv('DGM_ALLOW_EMPTY_GPU_ORDERS') ?: '';

        return filter_var($value, FILTER_VALIDATE_BOOL) === true;
    }

    public function isGpuOrderIdentifier(string $identifier): bool
    {
        return str_starts_with(strtoupper(trim($identifier)), 'GPU-');
    }

    public function createOrder(array $data): array
    {
        return $this->request('POST', '/integration/orders', $data);
    }

    /** @return list<array<string, mixed>> */
    public function getProducts(): array
    {
        return $this->request('GET', '/integration/products');
    }

    /** @return list<array<string, mixed>> */
    public function getNodes(): array
    {
        return $this->request('GET', '/integration/nodes');
    }

    /** @return list<array<string, mixed>> */
    public function getManagedNodes(): array
    {
        return $this->request('GET', '/integration/admin/nodes');
    }

    /** @return array<string, mixed> */
    public function getManagedNode(int $id): array
    {
        return $this->request('GET', '/integration/admin/nodes/' . $id);
    }

    /** @param array<string, mixed> $data */
    public function createManagedNode(array $data): array
    {
        return $this->request('POST', '/integration/admin/nodes', $data);
    }

    /** @param array<string, mixed> $data */
    public function updateManagedNode(int $id, array $data): array
    {
        return $this->request('PUT', '/integration/admin/nodes/' . $id, $data);
    }

    public function setManagedNodeShelf(int $id, bool $isOnShelf): void
    {
        $this->request('PATCH', '/integration/admin/nodes/' . $id . '/shelf', [
            'isOnShelf' => $isOnShelf,
        ]);
    }

    public function deleteManagedNode(int $id): void
    {
        $this->request('DELETE', '/integration/admin/nodes/' . $id);
    }

    public function getOrder(int $id): array
    {
        return $this->request('GET', '/integration/orders/' . $id);
    }

    public function applyAction(int $id, string $action): array
    {
        return $this->request('POST', '/integration/orders/action', ['id' => $id, 'action' => $action]);
    }

    private function request(string $method, string $path, array $data = []): array
    {
        $options = ['headers' => ['X-Integration-Key' => $this->apiKey(), 'Accept' => 'application/json']];
        if ($data !== []) {
            $options['json'] = $data;
        }
        $payload = $this->httpClient->request($method, $this->baseUrl() . $path, $options)->toArray(false);
        if (($payload['code'] ?? -1) !== 0) {
            throw new RuntimeException($payload['msg'] ?? 'Docker GPU Manage request failed');
        }
        return $payload['data'] ?? [];
    }

    private function baseUrl(): string
    {
        return rtrim((string) ($_ENV['DGM_API_URL'] ?? getenv('DGM_API_URL') ?: ''), '/');
    }

    private function apiKey(): string
    {
        return (string) ($_ENV['DGM_API_KEY'] ?? getenv('DGM_API_KEY') ?: '');
    }
}
