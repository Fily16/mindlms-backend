<?php
// MindLMS: avisa al backend cuando un estudiante publica en Moodle.

namespace local_mindlms\privacy;

defined('MOODLE_INTERNAL') || die();

/**
 * El plugin no guarda datos: solo envía el tipo de evento e IDs.
 */
class provider implements \core_privacy\local\metadata\null_provider {

    public static function get_reason(): string {
        return 'privacy:metadata';
    }
}
