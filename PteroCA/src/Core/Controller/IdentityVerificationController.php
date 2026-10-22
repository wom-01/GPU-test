<?php

namespace App\Core\Controller;

use App\Core\Entity\User;
use App\Core\Repository\UserRepository;
use App\Core\Service\Identity\AliyunRealNameService;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\HttpFoundation\Response;
use Symfony\Component\Routing\Annotation\Route;

class IdentityVerificationController extends AbstractController
{
    #[Route('/identity-verification', name: 'identity_verification', methods: ['GET'])]
    public function index(Request $request, AliyunRealNameService $service): Response
    {
        if ($request->attributes->get('_route') === 'identity_verification') {
            return $this->redirectToRoute('panel', ['routeName' => 'identity_verification_page']);
        }

        return $this->render('panel/account/identity_verification.html.twig', [
            'verificationEnabled' => $service->isEnabled(),
            'verificationConfigured' => $service->isConfigured(),
            'user' => $this->getUser(),
        ]);
    }

    #[Route('/identity-verification/start', name: 'identity_verification_start', methods: ['POST'])]
    public function start(Request $request, AliyunRealNameService $service, UserRepository $users): Response
    {
        if (!$this->isCsrfTokenValid('identity_verification', (string) $request->request->get('_token'))) {
            throw $this->createAccessDeniedException('Invalid CSRF token.');
        }

        $name = trim((string) $request->request->get('real_name'));
        $idNumber = strtoupper(trim((string) $request->request->get('id_number')));
        if ($name === '' || !preg_match('/^(\d{17}[0-9X]|\d{15})$/', $idNumber)) {
            $this->addFlash('danger', '请填写正确的姓名和身份证号码。');
            return $this->redirectToRoute('panel', ['routeName' => 'identity_verification_page']);
        }

        if (!$request->request->getBoolean('consent')) {
            $this->addFlash('danger', '请先同意实名认证信息处理规则。');
            return $this->redirectToRoute('panel', ['routeName' => 'identity_verification_page']);
        }

        /** @var User $user */
        $user = $this->getUser();
        try {
            $result = $service->start($name, $idNumber, $user->getId());
            $user->setRealNameStatus('pending')->setRealNameCertifyId($result['certifyId']);
            $users->save($user);
            return $this->redirect($result['url']);
        } catch (\Throwable $exception) {
            $this->addFlash('danger', $exception->getMessage());
            return $this->redirectToRoute('panel', ['routeName' => 'identity_verification_page']);
        }
    }
}
