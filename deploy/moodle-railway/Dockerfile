FROM moodlehq/moodle-php-apache:8.3-bookworm

# Moodle 4.5 LTS fijado al commit que corre en Railway desde el 2026-09-12
# (4.5.13+, versión 2024100713.03). La plantilla original clona la rama
# MOODLE_405_STABLE, así que cada redespliegue traía una versión nueva y
# obligaba a actualizar el núcleo de Moodle junto con cualquier otro cambio.
# safe.directory: en la imagen base /var/www/html es de www-data y git se
# niega a operar como root en un repo ajeno ("dubious ownership").
ARG MOODLE_COMMIT=96350aed80df2254de31f8f0325fb1aa149aa6b5
RUN git init -q /var/www/html \
 && git -c safe.directory=/var/www/html -C /var/www/html fetch -q --depth 1 https://github.com/moodle/moodle.git "$MOODLE_COMMIT" \
 && git -c safe.directory=/var/www/html -C /var/www/html checkout -q FETCH_HEAD \
 && rm -rf /var/www/html/.git \
 && chown -R www-data:www-data /var/www/html

# Plugin de MindLMS: avisa al backend cuando un estudiante publica.
COPY local_mindlms /var/www/html/local/mindlms
RUN chown -R www-data:www-data /var/www/html/local/mindlms

# Install and configure the runtime entrypoint
COPY railway-entrypoint.sh /usr/local/bin/railway-entrypoint.sh
RUN chmod +x /usr/local/bin/railway-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/railway-entrypoint.sh"]
