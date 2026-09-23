#!/usr/bin/env bash
set -euo pipefail

# Ensure only one MPM module is enabled (prefork)
a2dismod mpm_event mpm_worker >/dev/null 2>&1 || true
a2enmod mpm_prefork >/dev/null 2>&1 || true

# Remove any leftover symlinks that could cause conflicts
rm -f /etc/apache2/mods-enabled/mpm_event.* /etc/apache2/mods-enabled/mpm_worker.* || true
ln -sf /etc/apache2/mods-available/mpm_prefork.load /etc/apache2/mods-enabled/mpm_prefork.load || true
ln -sf /etc/apache2/mods-available/mpm_prefork.conf /etc/apache2/mods-enabled/mpm_prefork.conf || true

# Fix permissions for the Railway Volume (moodledata)
mkdir -p /var/www/moodledata
chown -R www-data:www-data /var/www/moodledata
chmod -R 0775 /var/www/moodledata

# Log which MPM module is loaded
apache2ctl -M 2>/dev/null | grep mpm || true

# Railway reverse-proxy: treat request as HTTPS when the proxy indicates it
echo "SetEnvIf X-Forwarded-Proto https HTTPS=on" > /etc/apache2/conf-available/railway-proxy.conf
a2enconf railway-proxy >/dev/null 2>&1 || true

# --- MindLMS: config.php generado en cada arranque ---------------------
# En Railway el sistema de archivos del contenedor se recrea en cada
# despliegue, asi que un config.php escrito por el instalador web se
# pierde y el sitio vuelve al instalador. Generarlo aqui lo hace
# reproducible y permite fijar ajustes que el instalador no pone:
#   sslproxy           -> el TLS lo termina el proxy, no Apache
#   getremoteaddrconf  -> ver el comentario dentro del config
#   local_mindlms      -> a donde avisa el plugin y con que secreto firma
if [ -n "${MOODLE_DB_HOST:-}" ]; then
  cat > /var/www/html/config.php <<PHPCONF
<?php  // Generado por railway-entrypoint.sh
unset(\$CFG);
global \$CFG;
\$CFG = new stdClass();

\$CFG->dbtype    = '${MOODLE_DB_TYPE:-pgsql}';
\$CFG->dblibrary = 'native';
\$CFG->dbhost    = '${MOODLE_DB_HOST}';
\$CFG->dbname    = '${MOODLE_DB_NAME}';
\$CFG->dbuser    = '${MOODLE_DB_USER}';
\$CFG->dbpass    = '${MOODLE_DB_PASS}';
\$CFG->prefix    = '${MOODLE_DB_PREFIX:-mdl_}';
\$CFG->dboptions = array(
    'dbpersist' => 0,
    'dbport'    => '${MOODLE_DB_PORT:-5432}',
    'dbsocket'  => '',
    'dbcollation' => 'utf8mb4_unicode_ci',
);

\$CFG->wwwroot   = '${MOODLE_WWWROOT}';
\$CFG->dataroot  = '/var/www/moodledata';
\$CFG->admin     = 'admin';
\$CFG->directorypermissions = 0777;

\$CFG->sslproxy = true;

// El proxy de Railway entrega cada peticion desde una IP interna
// distinta (100.64.0.x). Moodle, que descarta la sesion cuando la IP
// cambia, creaba una sesion nueva en cada salto: de ahi el bucle entre
// ?cache=1 y ?sessionstarted=1 y el error 'installhijacked'. Con esto
// lee la IP real del cliente desde X-Forwarded-For, que si es estable.
\$CFG->getremoteaddrconf = 0;

// Plugin local_mindlms: sin URL o sin secreto no envia nada.
\$CFG->forced_plugin_settings = array(
    'local_mindlms' => array(
        'webhookurl'    => '${MINDLMS_WEBHOOK_URL:-}',
        'webhooksecret' => '${MINDLMS_WEBHOOK_SECRET:-}',
    ),
);

require_once(__DIR__ . '/lib/setup.php');
PHPCONF
  chown www-data:www-data /var/www/html/config.php
  echo "config.php generado para ${MOODLE_WWWROOT}"
else
  echo "MOODLE_DB_HOST no definido: se conserva el config.php existente"
fi

# --- MindLMS: purgar cachés de Moodle en cada arranque -----------------
# admin/index.php compara $CFG->version (que sale de la caché guardada en
# moodledata) contra la version de la base de datos y, si no coinciden,
# purga y redirige. Como moodledata es un volumen persistente, una caché
# quedada de una instalacion anterior sobrevive a los despliegues y deja
# el sitio en un bucle de redirecciones permanente.
rm -rf /var/www/moodledata/cache/* \
       /var/www/moodledata/localcache/* \
       /var/www/moodledata/muc/* \
       /var/www/moodledata/temp/* \
       /var/www/moodledata/sessions/* 2>/dev/null || true
echo "cachés de moodledata purgadas"

# --- MindLMS: instalar/actualizar plugins antes de abrir el sitio ------
# Un plugin nuevo (como local_mindlms) no funciona hasta que Moodle lo
# registra en la base de datos. Si no hay nada pendiente, no hace nada.
# Si falla, el sitio arranca igual y el aviso queda en los logs.
if [ -f /var/www/html/config.php ]; then
  su -s /bin/sh www-data -c "/usr/local/bin/php /var/www/html/admin/cli/upgrade.php --non-interactive" \
    || echo "upgrade.php fallo: revisar /admin/index.php en el navegador"
fi

# Start the original entrypoint + Apache
exec /usr/local/bin/moodle-docker-php-entrypoint apache2-foreground
