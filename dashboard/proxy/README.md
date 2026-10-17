# Proxy "Air Majoro Dashboard"

Proxy Node.js sin dependencias que reescribe la salida de Evidence **sin modificar su código**.
Así los cambios sobreviven a las actualizaciones de Evidence.

## Cómo funciona

```
Navegador -> localhost:4000 (proxy) -> localhost:4001 (Evidence)
```

El proxy, en cada respuesta HTML:
1. Reescribe el `<title>` y los textos server-rendered (desde `translations.txt`).
2. Reescribe el `<link rel="icon">` para usar el favicon propio (`favico.ico`).
3. Inyecta un `<style>` para ocultar componentes (desde `hide.txt`).
4. Inyecta un `<script>` que:
   - cambia los textos renderizados en el cliente (menús desplegables, etc.),
   - corrige el título al navegar,
   - **fuerza el modo claro siempre** (quita la clase `dark` y el toggle de tema).

## Uso

1. Arranca Evidence en el puerto **4001**:
   ```bash
   evidence dev --port 4001
   ```
2. Arranca el proxy (escucha en **4000**):
   ```bash
   node proxy/proxy.mjs
   ```
3. Abre: **http://localhost:4000**

## Configuración

- **`translations.txt`** — traducciones. Formato `texto original => traducción`.
  La entrada `Evidence` define además el prefijo del título de la pestaña.
- **`hide.txt`** — selectores CSS (uno por línea) para ocultar componentes.
- **`favico.ico`** — favicon de la página. El proxy lo sirve directamente en
  `/favico.ico`, `/favicon.ico` y `/favicon.svg`, y reescribe el `<link rel="icon">`.
  Para cambiarlo, sustituye el archivo y reinicia el proxy.

### Tipografía (Poppins)

La tipografía del informe se aplica **desde el proxy**, no desde `theme.yaml`:
el token `fonts` de Evidence solo admite `sans-serif | serif | mono` (fuentes
empaquetadas), así que una fuente propia como Poppins no se puede declarar allí.

En `proxy.mjs`:

- se carga **Poppins** desde Google Fonts (`FONT_GOOGLE_URL`),
- se sobrescriben las variables de tema de Evidence (`--theme-font-body`,
  `--theme-font-heading`, `--theme-font-mono`, `--evidence-font-*`),
- se parchea `CanvasRenderingContext2D.font` para que **los gráficos ECharts**
  (texto en `<canvas>`, donde el CSS no aplica) también usen Poppins,
- al terminar de cargar la fuente se dispara un `resize` para re-renderizar los
  gráficos con la fuente ya disponible.

Para cambiar de fuente, edita `FONT_FAMILY`, `FONT_FAMILY_MONO` y
`FONT_GOOGLE_URL` y **reinicia el proxy**. También puedes auto-hospedar la
fuente desde el propio proxy si el informe no tiene acceso a internet.

Tras editar los `.txt`, **reinicia el proxy** para recargarlos.

## Variables de entorno

| Variable         | Por defecto | Descripción                       |
| ---------------- | ----------- | --------------------------------- |
| `PORT`           | `4000`      | Puerto donde escucha el proxy     |
| `UPSTREAM_PORT`  | `4001`      | Puerto donde corre Evidence       |
| `UPSTREAM_HOST`  | `localhost` | Host donde corre Evidence         |
| `FORCE_LIGHT`    | `true`      | `false` para permitir modo oscuro |
