const express = require("express");
const bodyParser = require("body-parser");
const axios = require("axios");

const TELEGRAM_TOKEN = process.env.TELEGRAM_TOKEN; // vem do Render
const CHAT_ID = process.env.CHAT_ID; // vem do Render

const app = express();
app.use(bodyParser.json());

// Rota que a TriboPay vai chamar
app.post("/webhook/tribopay", async (req, res) => {
  console.log("Webhook recebido:", req.body);

  const status = req.body.status;
  const nome = req.body.customer?.name;

  if (status === "paid") {
    await axios.post(`https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage`, {
      chat_id: CHAT_ID,
      text: `✅ Pagamento confirmado para *${nome}*! Bem-vindo(a) ao grupo VIP 🔥`,
      parse_mode: "Markdown"
    });
  }

  res.json({ ok: true });
});

// Render exige usar a porta da variável de ambiente PORT
const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Servidor rodando na porta ${PORT}`));
