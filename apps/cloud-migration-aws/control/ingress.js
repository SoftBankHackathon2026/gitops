// Cloud entrypoint for the existing sample-app image; no onprem default.
const express = require('/app/node_modules/express');
const {createClient} = require('/app/node_modules/redis');
const {createIngress, controlAuth} = require('/app/src/durable-ingress/service');

async function main() {
  if (!process.env.INGRESS_INITIAL_TARGET || !process.env.INGRESS_API_TOKEN || !process.env.INGRESS_CONTROL_TOKEN) {
    throw new Error('AUTH_REQUIRED');
  }
  const targets = JSON.parse(process.env.INGRESS_TARGETS);
  for (const target of Object.values(targets)) {
    if (target.token_env) {
      target.token = process.env[target.token_env];
      if (!target.token) throw new Error('TARGET_TOKEN_REQUIRED');
    }
  }
  const redis = createClient({url: process.env.REDIS_URL,
    disableOfflineQueue: true, socket: {connectTimeout: 3000}});
  redis.on('error', () => {});
  await redis.connect();
  const app = await createIngress({redis, targets,
    initialTarget: process.env.INGRESS_INITIAL_TARGET,
    controlToken: process.env.INGRESS_CONTROL_TOKEN});
  const external = express(); external.disable('x-powered-by');
  external.use('/api', controlAuth(process.env.INGRESS_API_TOKEN));
  external.use(app.api);
  const api = external.listen(8080, '0.0.0.0');
  const control = app.control.listen(9092, '0.0.0.0');
  process.once('SIGTERM', async () => {
    api.close(); control.close(); await app.close(); await redis.quit();
  });
}
main().catch(() => { console.error('CLOUD_INGRESS_START_FAILED'); process.exit(1); });
