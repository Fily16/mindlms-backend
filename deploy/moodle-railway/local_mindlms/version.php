<?php
// MindLMS: avisa al backend cuando un estudiante publica en Moodle.

defined('MOODLE_INTERNAL') || die();

$plugin->component = 'local_mindlms';
$plugin->version   = 2026092200;
$plugin->requires  = 2024100700; // Moodle 4.5.
$plugin->maturity  = MATURITY_STABLE;
$plugin->release   = '1.0';
