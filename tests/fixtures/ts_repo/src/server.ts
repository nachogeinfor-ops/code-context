/**
 * server.ts — Entry point. Creates the Express app and starts HTTP listener.
 */

import { createApp } from "./app";
import { getConfig } from "./config";

const config = getConfig();
const app = createApp();

app.listen(config.PORT, () => {
  console.log(`Server listening on port ${config.PORT} [${config.NODE_ENV}]`);
});

// Graceful shutdown
process.on("SIGTERM", () => {
  console.log("SIGTERM received — shutting down");
  process.exit(0);
});
