<?php

/**
 * Router script for PHP built-in web server
 * This script enables pretty URLs by routing all requests through index.php
 *
 * Usage: php -S localhost:8000 -t public/ public/router.php
 *
 * WARNING: This is for DEVELOPMENT ONLY!
 * DO NOT use PHP built-in server in production. Use nginx/Apache + PHP-FPM instead.
 */

if (php_sapi_name() !== 'cli-server') {
    die('This script can only be run by the PHP built-in web server.');
}

// Get the requested path
$path = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);

// Security: Block path traversal attempts
if (str_contains($path, '..')) {
    http_response_code(403);
    die('Forbidden: Path traversal attempt detected');
}

// ── 聚算并网南向接口(/api/v1/*)：转发到本机 FastAPI 服务(127.0.0.1:12359) ──
// 其余请求仍走原 Symfony 前端控制器；文档页 /docs、/openapi.json 一并代理便于调试
if (str_starts_with($path, '/api/v1/') || str_starts_with($path, '/static/') || in_array($path, ['/docs', '/openapi.json', '/healthz', '/docs/oauth2-redirect'], true)) {
    $upstream = 'http://127.0.0.1:12359' . $_SERVER['REQUEST_URI'];
    $forwardHeaders = [];
    foreach ($_SERVER as $key => $value) {
        if (str_starts_with($key, 'HTTP_')) {
            $name = str_replace(' ', '-', ucwords(strtolower(str_replace('_', ' ', substr($key, 5)))));
            if (in_array($name, ['Authorization', 'Content-Type', 'Accept'], true)) {
                $forwardHeaders[] = "$name: $value";
            }
        }
    }
    if (!empty($_SERVER['REMOTE_ADDR'])) {
        $forwardHeaders[] = 'X-Forwarded-For: ' . $_SERVER['REMOTE_ADDR'];
    }
    $context = stream_context_create(['http' => [
        'method'        => $_SERVER['REQUEST_METHOD'],
        'header'        => implode("\r\n", $forwardHeaders),
        'content'       => file_get_contents('php://input'),
        'ignore_errors' => true,
        'timeout'       => 15,
    ]]);
    $body = @file_get_contents($upstream, false, $context);
    if ($body === false) {
        http_response_code(502);
        header('Content-Type: application/json; charset=UTF-8');
        die(json_encode(['code' => '502', 'message' => '并网南向接口服务暂不可用', 'data' => []]));
    }
    foreach ($http_response_header as $rh) {
        if (preg_match('#^HTTP/\S+\s+(\d{3})#', $rh, $m)) {
            http_response_code((int) $m[1]);
        } elseif (preg_match('#^(content-type|retry-after):#i', $rh)) {
            header($rh);
        }
    }
    die($body);
}

// Get the absolute path to the file (follows symlinks)
$filePath = __DIR__ . $path;

// If the requested file exists AND it's a file (not a directory), serve it directly
// This handles static assets (including symlinked plugin assets)
if ($path !== '/' && is_file($filePath)) {
    return false; // serve the requested file as-is
}

// Otherwise, route everything through Symfony's front controller
$_SERVER['SCRIPT_FILENAME'] = __DIR__ . '/index.php';
$_SERVER['SCRIPT_NAME'] = '/index.php';

require __DIR__ . '/index.php';
