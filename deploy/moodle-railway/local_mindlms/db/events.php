<?php
// Eventos que disparan una detección en MindLMS.
//
// 'internal' => false: el observador corre DESPUÉS de que la transacción
// se confirma. Si corriera dentro, el backend podría consultar Moodle antes
// de que el post exista para las demás conexiones y no lo encontraría.

defined('MOODLE_INTERNAL') || die();

$observers = [
    [
        'eventname' => '\mod_forum\event\discussion_created',
        'callback'  => '\local_mindlms\observer::avisar',
        'internal'  => false,
    ],
    [
        'eventname' => '\mod_forum\event\post_created',
        'callback'  => '\local_mindlms\observer::avisar',
        'internal'  => false,
    ],
    [
        'eventname' => '\core\event\message_sent',
        'callback'  => '\local_mindlms\observer::avisar',
        'internal'  => false,
    ],
    [
        'eventname' => '\mod_chat\event\message_sent',
        'callback'  => '\local_mindlms\observer::avisar',
        'internal'  => false,
    ],
];
