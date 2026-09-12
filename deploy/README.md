# Despliegue de la API en una VM (Oracle Cloud Always Free)

Pasos para dejar la API corriendo en una VM Ubuntu 24.04 ARM (Ampere A1).
Pensado para 1 OCPU / 6 GB, que es donde entra RoBERTa con holgura.

## 1. Dependencias del sistema

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip nginx certbot python3-certbot-nginx git
```

## 2. Código y entorno virtual

```bash
git clone https://github.com/Fily16/mindlms-backend.git ~/mindlms-backend
cd ~/mindlms-backend
python3.11 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

En ARM64 pip instala la build CPU de torch automáticamente, sin arrastrar
los paquetes CUDA que en x86 añaden varios GB inútiles.

## 3. Variables de entorno

Copiar `.env.example` a `.env` y completar. Las que no pueden quedarse con
su valor por defecto:

| Variable | Valor |
|---|---|
| `SECRET_KEY` | Generar: `openssl rand -hex 32`. Nunca el `change-this-...` |
| `POSTGRES_URL` | La URI de Aiven, como `postgresql+asyncpg://...?ssl=require` |
| `MONGODB_URL` | La URI de MongoDB Atlas |
| `ROBERTA_MODEL_ID` | El repo del modelo en Hugging Face Hub |
| `CORS_ORIGINS` | `["https://<tu-app>.vercel.app"]` — **formato JSON**, no separado por comas |
| `DEBUG` | `false` |
| `AUTO_TRAIN_ON_STARTUP` | `false` |
| `MOODLE_URL` / `MOODLE_TOKEN` | Del Moodle desplegado |

## 4. Servicio y proxy

```bash
sudo cp deploy/mindlms-api.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now mindlms-api

sudo cp deploy/nginx-mindlms.conf /etc/nginx/sites-available/mindlms
sudo ln -s /etc/nginx/sites-available/mindlms /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d <TU_DOMINIO>
```

## 5. Red (los dos cortafuegos)

Oracle tiene **dos** capas y olvidar la segunda es el error más común:

1. En la consola de Oracle: *Security List* de la subred → permitir 80 y 443.
2. En la propia VM (las imágenes de Oracle traen iptables restrictivo):

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

## 6. Usuario inicial del dashboard

```bash
PSYCHOLOGIST_PASSWORD='<una contraseña fuerte>' .venv/bin/python scripts/create_psychologist.py
```

## 7. Comprobar que RoBERTa cargó de verdad

El clasificador degrada en silencio a Random Forest o a reglas si el modelo
falla, así que hay que verificarlo explícitamente:

```bash
journalctl -u mindlms-api | grep -i "modelo"
# Debe decir: "Modelo RoBERTa cargado desde ..."
curl -s https://<TU_DOMINIO>/health
```

Y al lanzar una detección, el evento SSE `new_alert` debe traer
`model_backend: "transformer"`.
