<?php
// MindLMS: avisa al backend cuando un estudiante publica en Moodle.

namespace local_mindlms;

defined('MOODLE_INTERNAL') || die();

/**
 * Envía a MindLMS un aviso firmado por cada publicación.
 *
 * El aviso solo lleva el tipo de evento e IDs, nunca el texto: el backend
 * lee lo nuevo por la API de Moodle, como en cualquier otra detección.
 */
class observer {

    /** Segundos máximos que el estudiante puede esperar por el aviso. */
    const TIMEOUT = 3;

    public static function avisar(\core\event\base $event): void {
        global $CFG;

        // Vienen de config.php (forced_plugin_settings), no de la interfaz.
        $url = get_config('local_mindlms', 'webhookurl');
        $secreto = get_config('local_mindlms', 'webhooksecret');
        if (empty($url) || empty($secreto)) {
            return;
        }

        $cuerpo = json_encode([
            'eventname'   => $event->eventname,
            'objectid'    => $event->objectid,
            'courseid'    => $event->courseid,
            'timecreated' => $event->timecreated,
        ]);

        require_once($CFG->libdir . '/filelib.php');
        $curl = new \curl();
        $curl->setHeader([
            'Content-Type: application/json',
            'X-Moodle-Signature: ' . hash_hmac('sha256', $cuerpo, $secreto),
        ]);

        // Si el backend está apagado, el aviso lo enciende aunque aquí se
        // agote la espera: al arrancar, la detección revisa lo pendiente.
        // Un fallo nunca debe impedir que el estudiante publique.
        try {
            $curl->post($url, $cuerpo, [
                'CURLOPT_TIMEOUT'        => self::TIMEOUT,
                'CURLOPT_CONNECTTIMEOUT' => self::TIMEOUT,
            ]);
            if ($curl->get_errno()) {
                debugging('local_mindlms: aviso no entregado: ' . $curl->error, DEBUG_DEVELOPER);
            }
        } catch (\Throwable $e) {
            debugging('local_mindlms: aviso no entregado: ' . $e->getMessage(), DEBUG_DEVELOPER);
        }
    }
}
