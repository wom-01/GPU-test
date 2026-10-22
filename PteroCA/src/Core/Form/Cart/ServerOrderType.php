<?php

namespace App\Core\Form\Cart;

use Symfony\Component\Form\AbstractType;
use Symfony\Component\Form\Extension\Core\Type\ChoiceType;
use Symfony\Component\Form\Extension\Core\Type\HiddenType;
use Symfony\Component\Form\Extension\Core\Type\IntegerType;
use Symfony\Component\Form\Extension\Core\Type\PasswordType;
use Symfony\Component\Form\Extension\Core\Type\TextType;
use Symfony\Component\Form\FormBuilderInterface;
use Symfony\Component\OptionsResolver\OptionsResolver;
use Symfony\Component\Validator\Constraints as Assert;

/**
 * Form type for server ordering/configuration.
 *
 * Used in cart_configure and cart_buy routes.
 */
class ServerOrderType extends AbstractType
{
    public function buildForm(FormBuilderInterface $builder, array $options): void
    {
        $builder
            ->add('id', HiddenType::class, [
                'data' => $options['product_id'],
                'constraints' => [
                    new Assert\NotBlank(),
                    new Assert\Positive(),
                ],
            ])
            ->add('egg', ChoiceType::class, [
                'choices' => $options['eggs'],
                'data' => $options['selected_egg'],
                'label' => false,
                'required' => true,
                'mapped' => false,
                'constraints' => [
                    new Assert\NotBlank(message: 'pteroca.store.please_select_game'),
                ],
                'attr' => [
                    'class' => 'form-select form-select-lg',
                ],
            ])
            ->add('duration', ChoiceType::class, [
                'choices' => $options['prices'],
                'choice_attr' => function ($choice) use ($options) {
                    return $options['price_choice_attrs'][$choice] ?? [];
                },
                'data' => $options['selected_duration'],
                'label' => false,
                'required' => true,
                'mapped' => false,
                'constraints' => [
                    new Assert\NotBlank(message: 'pteroca.store.please_select_duration'),
                ],
                'attr' => [
                    'class' => 'form-select form-select-lg',
                ],
            ])
            ->add('server-name', TextType::class, [
                'label' => 'pteroca.store.server_name',
                'required' => false,
                'constraints' => [
                    new Assert\Length(
                        max: 50,
                        maxMessage: 'pteroca.store.server_name_too_long'
                    ),
                ],
                'attr' => [
                    'class' => 'form-control',
                    'placeholder' => 'pteroca.store.enter_server_name',
                ],
            ])
            ->add('operating-system', ChoiceType::class, [
                'label' => false,
                'required' => true,
                'choices' => [
                    'Ubuntu 22.04 LTS' => 'ubuntu-22.04',
                    'Ubuntu 24.04 LTS' => 'ubuntu-24.04',
                    'Debian 12' => 'debian-12',
                    'Rocky Linux 9' => 'rocky-linux-9',
                    'Windows Server 2022' => 'windows-server-2022',
                ],
                'data' => $options['selected_operating_system'],
                'constraints' => [new Assert\NotBlank(message: '请选择操作系统')],
                'attr' => ['class' => 'form-select form-select-lg'],
            ])
            ->add('ssh-password', PasswordType::class, [
                'label' => false,
                'required' => true,
                'always_empty' => false,
                'data' => $options['initial_ssh_password'],
                'constraints' => [
                    new Assert\NotBlank(message: '请设置服务器登录密码'),
                    new Assert\Length(min: 8, max: 64, minMessage: '登录密码至少需要 8 位', maxMessage: '登录密码不能超过 64 位'),
                    new Assert\Regex(pattern: '/^(?=.*[A-Za-z])(?=.*\d).+$/', message: '登录密码必须同时包含字母和数字'),
                ],
                'attr' => [
                    'class' => 'form-control form-control-lg',
                    'autocomplete' => 'new-password',
                    'placeholder' => '8-64 位，必须包含字母和数字',
                ],
            ]);

        if ($options['allow_auto_renewal']) {
            $builder->add('auto-renewal', ChoiceType::class, [
                'label' => 'pteroca.cart_configuration.auto_renewal',
                'choices' => [
                    'pteroca.cart_configuration.enable' => '1',
                    'pteroca.cart_configuration.disable' => '0',
                ],
                'data' => '0',
                'required' => true,
                'attr' => [
                    'class' => 'form-select form-select-lg',
                ],
            ]);
        }

        if ($options['allow_location_selection']) {
            $builder->add('node', ChoiceType::class, [
                'label' => 'pteroca.cart_configuration.location',
                'choices' => $this->buildLocationChoices($options['grouped_locations']),
                'required' => true,
                'mapped' => false,
                'constraints' => [
                    new Assert\NotBlank(message: 'pteroca.store.please_select_location'),
                ],
                'attr' => [
                    'class' => 'form-select form-select-lg',
                    'id' => 'location',
                ],
            ]);
        }

        $builder->add('voucher', HiddenType::class, [
                'required' => false,
                'data' => '',
            ]);

        if ($options['has_slot_prices']) {
            $builder->add('slots', IntegerType::class, [
                'label' => 'pteroca.store.slots',
                'required' => true,
                'data' => $options['initial_slots'],
                'constraints' => [
                    new Assert\NotBlank(message: 'pteroca.store.slots_required'),
                    new Assert\Positive(message: 'pteroca.store.slots_must_be_positive'),
                ],
                'attr' => [
                    'class' => 'form-control',
                    'min' => 1,
                    'style' => 'display:none',
                ],
                'label_attr' => [
                    'style' => 'display:none',
                ],
            ]);
        }
    }

    private function buildLocationChoices(?array $groupedLocations): array
    {
        if (empty($groupedLocations)) {
            return [];
        }

        $choices = [];
        foreach ($groupedLocations as $locationName => $locationData) {
            $choices[$locationName] = [];
            foreach ($locationData['nodes'] as $node) {
                $choices[$locationName][$node['name']] = $node['id'];
            }
        }

        return $choices;
    }

    public function configureOptions(OptionsResolver $resolver): void
    {
        $resolver->setDefaults([
            'product_id' => null,
            'eggs' => [],
            'prices' => [],
            'price_choice_attrs' => [],
            'selected_duration' => null,
            'selected_egg' => null,
            'selected_operating_system' => 'ubuntu-22.04',
            'initial_ssh_password' => null,
            'has_slot_prices' => false,
            'initial_slots' => null,
            'allow_auto_renewal' => true,
            'allow_location_selection' => false,
            'grouped_locations' => null,
            'csrf_protection' => true,
            'csrf_field_name' => '_token',
            'csrf_token_id' => 'server_order',
        ]);

        $resolver->setRequired(['product_id', 'eggs', 'prices']);
        $resolver->setAllowedTypes('product_id', 'int');
        $resolver->setAllowedTypes('eggs', 'array');
        $resolver->setAllowedTypes('prices', 'array');
        $resolver->setAllowedTypes('price_choice_attrs', 'array');
        $resolver->setAllowedTypes('selected_duration', ['int', 'null']);
        $resolver->setAllowedTypes('selected_egg', ['int', 'null']);
        $resolver->setAllowedTypes('selected_operating_system', ['string', 'null']);
        $resolver->setAllowedTypes('initial_ssh_password', ['string', 'null']);
        $resolver->setAllowedTypes('has_slot_prices', 'bool');
        $resolver->setAllowedTypes('initial_slots', ['int', 'null']);
        $resolver->setAllowedTypes('allow_auto_renewal', 'bool');
        $resolver->setAllowedTypes('allow_location_selection', 'bool');
        $resolver->setAllowedTypes('grouped_locations', ['array', 'null']);
    }
}
