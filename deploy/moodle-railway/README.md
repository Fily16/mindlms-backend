# Moodle de MindLMS en Railway

Imagen del Moodle de pruebas desplegado en Railway
(`moodle-production-17c5.up.railway.app`, proyecto `authentic-tranquility`,
servicio `Moodle`). Parte de la plantilla MIT
[JesseZweers/moodle-railway](https://github.com/JesseZweers/moodle-railway)
(ver `LICENSE`) con estos cambios:

| Cambio | Por qué |
|---|---|
| Moodle fijado a un commit (4.5.13+, `2024100713.03`) | La plantilla sigue la rama estable: cada redespliegue actualizaba el núcleo sin pedirlo. |
| `config.php` generado en cada arranque | El disco del contenedor se recrea en cada despliegue y el `config.php` del instalador se perdía. |
| `sslproxy` y `getremoteaddrconf = 0` | El proxy de Railway termina el TLS y cambia la IP interna en cada petición: sin esto, bucle de redirecciones e `installhijacked`. |
| Purga de cachés de `moodledata` al arrancar | Una caché vieja en el volumen persistente mantenía el bucle vivo entre despliegues. |
| `upgrade.php` al arrancar | Registra plugins nuevos (como `local_mindlms`) sin pasar por la interfaz. |
| Plugin `local_mindlms` | Avisa al backend cuando un estudiante publica. |

## Plugin `local_mindlms`

Observa `discussion_created` y `post_created` de foros, `message_sent` de
mensajería y de chat. En cada uno envía un POST a `MINDLMS_WEBHOOK_URL` con
el tipo de evento e IDs (nunca el texto), firmado con HMAC-SHA256 en la
cabecera `X-Moodle-Signature`. El backend (`POST /api/v1/moodle/webhook`)
valida la firma y lanza la detección de siempre, que lee lo nuevo por la API
de Moodle.

El aviso corre después de confirmarse la transacción y espera como máximo
3 s: si el backend está apagado, la petición lo enciende y la detección de
arranque revisa lo pendiente. Un fallo nunca impide publicar.

## Variables del servicio `Moodle` en Railway

| Variable | Valor |
|---|---|
| `MOODLE_DB_TYPE`, `MOODLE_DB_HOST`, `MOODLE_DB_PORT`, `MOODLE_DB_NAME`, `MOODLE_DB_USER`, `MOODLE_DB_PASS` | Conexión al servicio `Postgres` del mismo proyecto |
| `MOODLE_WWWROOT` | `https://moodle-production-17c5.up.railway.app` |
| `MINDLMS_WEBHOOK_URL` | `https://yanfilybacatorres--mindlms-api-fastapi-app.modal.run/api/v1/moodle/webhook` |
| `MINDLMS_WEBHOOK_SECRET` | El mismo valor que `MOODLE_WEBHOOK_SECRET` del secreto `mindlms-webhook` de Modal |

## Desplegar

```bash
cd backend/deploy/moodle-railway
railway link --project f2680fe4-0f92-4b33-83ae-19d56c7dd8b9 --environment production --service Moodle
railway up . --path-as-root --service Moodle --detach
```

`--path-as-root` es obligatorio: sin él Railway sube todo el repo y construye
el `Dockerfile` del backend dentro del servicio de Moodle.

Antes de redesplegar, respaldar la base de datos (`pg_dump --format=custom`
contra la `DATABASE_PUBLIC_URL` del servicio `Postgres`).
