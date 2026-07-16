const express = require("express");
const app = express();
app.get("/health", (_req, res) => res.send("ok"));
app.listen(8080);
