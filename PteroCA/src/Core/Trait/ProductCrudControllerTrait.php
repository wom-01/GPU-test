<?php

namespace App\Core\Trait;

use EasyCorp\Bundle\EasyAdminBundle\Field\FormField;
use Exception;

trait ProductCrudControllerTrait
{
    private array $flashMessages = [];

    private function getNodesChoices(): array
    {
        if (!empty($_ENV['DGM_API_URL'] ?? getenv('DGM_API_URL')) && property_exists($this, 'dockerGpuManageClient')) {
            try {
                $choices = [];
                foreach ($this->dockerGpuManageClient->getNodes() as $node) {
                    $id = (int) ($node['ID'] ?? $node['id'] ?? 0);
                    $name = (string) ($node['name'] ?? 'GPU 节点');
                    $region = (string) ($node['region'] ?? '未分区');
                    $publicIp = trim((string) ($node['publicIp'] ?? ''));
                    $status = strtolower((string) ($node['dockerStatus'] ?? 'unknown'));
                    if ($id > 0 && $status === 'connected') {
                        $label = $publicIp === ''
                            ? sprintf('%s · 已连接', $name)
                            : sprintf('%s · %s · 已连接', $name, $publicIp);
                        $choices[$region][$label] = $id;
                    }
                }
                return $choices;
            } catch (Exception $exception) {
                $this->flashMessages[] = 'GPU 算力节点同步失败：' . $exception->getMessage();
                return [];
            }
        }

        try {
            $nodes = $this->pterodactylApplicationService
                ->getApplicationApi()
                ->nodes()
                ->getAllNodes()
                ->toArray();
            $locations = [];
            $choices = [];

            foreach ($nodes as $node) {
                if (empty($locations[$node['location_id']])) {
                    $locations[$node['location_id']] = $this->pterodactylApplicationService
                        ->getApplicationApi()
                        ->locations()
                        ->get($node['location_id']);
                }
                $choices[$locations[$node['location_id']]['short']][$node['name']] = $node['id'];
            }

            return $choices;
        } catch (Exception $exception) {
            $this->flashMessages[] = $exception->getMessage();
            return [];
        }
    }

    private function getNestsChoices(): array
    {
        if (!empty($_ENV['DGM_API_URL'] ?? getenv('DGM_API_URL')) && property_exists($this, 'dockerGpuManageClient')) {
            try {
                $choices = [];
                foreach ($this->dockerGpuManageClient->getProducts() as $product) {
                    $id = (int) ($product['ID'] ?? $product['id'] ?? 0);
                    $name = (string) ($product['name'] ?? 'GPU');
                    if ($id > 0) {
                        $choices[$name] = $id;
                    }
                }
                return $choices;
            } catch (Exception $exception) {
                $this->flashMessages[] = 'GPU 商品同步失败：' . $exception->getMessage();
                return [];
            }
        }

        try {
            $nests = $this->pterodactylApplicationService
                ->getApplicationApi()
                ->nests()
                ->all()
                ->toArray();
            $choices = [];

            foreach ($nests as $nest) {
                $choices[$nest['name']] = $nest['id'];
            }

            return $choices;
        } catch (Exception $exception) {
            $this->flashMessages[] = $exception->getMessage();
            return [];
        }
    }

    private function getEggsChoices(array $nests): array
    {
        if (!empty($_ENV['DGM_API_URL'] ?? getenv('DGM_API_URL')) && property_exists($this, 'dockerGpuManageClient')) {
            return ['GPU 容器环境' => 1];
        }

        try {
            $choices = [];
            $nestNames = $this->getNestsChoices();

            foreach ($nests as $nestId) {
                $eggs = $this->nestEggsCacheService->getEggsForNest($nestId);
                $nestName = array_search($nestId, $nestNames) ?: "Nest $nestId";

                foreach ($eggs as $egg) {
                    $choices["[$nestName] {$egg['name']}"] = $egg['id'];
                }
            }

            return $choices;
        } catch (Exception $exception) {
            $this->flashMessages[] = $exception->getMessage();
            return [];
        }
    }

    private function getEggsConfigurationFromRequest(): array
    {
        $requestData = $this->requestStack->getCurrentRequest()->request->all();
        return $requestData['eggs_configuration'] ?? [];
    }

    private function getProductHelpPanel(): FormField
    {
        $helpText = sprintf(
            '<small class="text-muted"><a href="%s" target="_blank">%s</a></small>',
            'https://docs.pteroca.com/business-configuration/business-configuration/products-and-categories',
            $this->translator->trans('pteroca.crud.product.see_product_configuration_guide'),
        );

        return FormField::addPanel('')
                ->setHelp($helpText)
                ->hideOnIndex();
    }
}
