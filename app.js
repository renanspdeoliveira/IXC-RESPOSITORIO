const API = "http://34.72.28.65:8000";


const $ = (id) => document.getElementById(id);
const msg = (t = "") => ($("msg").textContent = t);

// ================= HELPERS =================
function pick(obj, keys, fallback = "—") {
  for (const k of keys) {
    const v = obj?.[k];
    if (v !== undefined && v !== null && String(v).trim() !== "") return v;
  }
  return fallback;
}

function parseFloatSafe(v) {
  if (v === undefined || v === null) return NaN;
  const n = Number(String(v).replace(",", ".").trim());
  return Number.isFinite(n) ? n : NaN;
}

function hasValue(v) {
  return v !== undefined && v !== null && String(v).trim() !== "" && String(v).trim() !== "—";
}

// ================= TEMPERATURA =================
function formatTempC(value) {
  if (!hasValue(value)) return "—";
  const n = parseFloatSafe(value);
  return Number.isFinite(n) ? `${n}ºC` : "—";
}

function tempCls(value) {
  const n = parseFloatSafe(value);
  if (!Number.isFinite(n)) return "sig-red";
  if (n <= 50) return "sig-green";
  if (n > 65) return "sig-red";
  if (n > 60) return "sig-orange";
  return "sig-blue";
}

// ================= RX / TX =================
function signalCls(value, forceRed = false) {
  if (forceRed) return "sig-red";

  const raw = parseFloatSafe(value);
  if (!Number.isFinite(raw)) return "sig-red";

  const v = Math.abs(raw);
  if (v >= 15.0 && v <= 23.99) return "sig-green";
  if (v > 23.99 && v <= 25.99) return "sig-blue";
  return "sig-red";
}

// ================= PON =================
function formatPonCentral(ponid) {
  if (!hasValue(ponid)) return "—";
  const parts = String(ponid).trim().split("-").map(p => p.trim()).filter(Boolean);
  return parts.slice(-2).join("-");
}

// ================= TEMPO =================
function parseTimestamp(ts) {
  if (!ts) return null;
  const d = new Date(String(ts).replace(" ", "T"));
  return isNaN(d.getTime()) ? null : d;
}

function formatUltimaConexaoComTempo(ts, ativo) {
  if (!ts) return "—";
  const d = parseTimestamp(ts);
  if (!d) return "—";

  if (ativo) return "00hr00m";

  const diff = Math.max(0, Math.floor((Date.now() - d.getTime()) / 60000));
  const h = String(Math.floor(diff / 60)).padStart(2, "0");
  const m = String(diff % 60).padStart(2, "0");
  return `${h}hr${m}m`;
}

// ================= API =================
async function apiGet(path) {
  const r = await fetch(`${API}${path}`);
  const t = await r.text();
  if (!r.ok) throw new Error(t);
  return JSON.parse(t);
}

// ================= RESET =================
function resetUI() {
  [
    "pppoe", "senhaPppoe", "ipv4", "mac",
    "ponOnu", "ultima", "rx", "tx", "temp",
    "at30", "os30", "atList", "osList",
    "superadminStatus"
  ].forEach(id => $(id).textContent = "—");

  $("rx").className = "sig-red";
  $("tx").className = "sig-red";
  $("temp").className = "";
  $("btnRouter").classList.add("hidden");

  $("atList").textContent = "Faça uma busca.";
  $("osList").textContent = "Faça uma busca.";
}

// ================= IPV4 =================
function isValidIPv4(ip) {
  return /^(\d{1,3}\.){3}\d{1,3}$/.test(ip);
}

function abrirRoteador(ip) {
  window.open(`https://${ip}:3031`, "_blank");
  setTimeout(() => {
    window.open(`http://${ip}:3031`, "_blank");
  }, 1500);
}

async function testarSuperAdmin(ip) {
  const urls = [
    `https://${ip}:3031/superadmin`,
    `http://${ip}:3031/superadmin`
  ];

  for (const url of urls) {
    try {
      await Promise.race([
        fetch(url, { mode: "no-cors" }),
        new Promise((_, r) => setTimeout(() => r("timeout"), 3000))
      ]);
      return true;
    } catch { }
  }
  return false;
}

// ================= CARD =================
function fillCard(resp) {
  const rad = resp.radusuarios || {};
  const pop = resp.radpop || {};

  const ipv4 = pick(rad, ["ip"], "—");
  const rxVal = pick(pop, ["sinal_rx"], "—");
  const txVal = pick(pop, ["sinal_tx"], "—");

  const ativo = hasValue(ipv4) && hasValue(rxVal) && hasValue(txVal);
  const forceRed = (!hasValue(ipv4) && !hasValue(rxVal) && !hasValue(txVal));

  $("pppoe").textContent = pick(rad, ["login"]);
  $("senhaPppoe").textContent = pick(rad, ["senha"]);
  $("ipv4").textContent = ipv4;

  // BOTÃO ROTEADOR
  if (isValidIPv4(ipv4)) {
    $("btnRouter").classList.remove("hidden");
    $("btnRouter").onclick = () => abrirRoteador(ipv4);
  }

  // SUPERADMIN
  const sa = $("superadminStatus");
  sa.textContent = "Verificando...";
  sa.className = "";

  if (isValidIPv4(ipv4)) {
    testarSuperAdmin(ipv4).then(ok => {
      sa.textContent = ok ? "ATIVO" : "DESABILITADO";
      sa.className = ok ? "sig-green" : "sig-red";
    });
  }

  $("mac").textContent = pick(pop, ["mac"], pick(rad, ["mac"]));

  const pon = formatPonCentral(pick(pop, ["ponid"]));
  const onu = pick(pop, ["onu_numero"]);
  $("ponOnu").textContent = `${pon} - ONU Nº: ${onu}`;

  $("ultima").textContent = formatUltimaConexaoComTempo(
    pick(rad, ["ultima_conexao_final", "ultima_conexao"]),
    ativo
  );

  $("rx").textContent = hasValue(rxVal) ? `${rxVal} dBm` : "—";
  $("rx").className = signalCls(rxVal, forceRed);

  $("tx").textContent = hasValue(txVal) ? `${txVal} dBm` : "—";
  $("tx").className = signalCls(txVal, forceRed);

  const tempRaw = pick(pop, ["temperatura"], "—");
  $("temp").textContent = formatTempC(tempRaw);
  $("temp").className = tempCls(tempRaw);
}

// ================= SUMMARY =================
function fillSummary(data) {
  $("at30").textContent = data.atendimentos_30d ?? 0;
  $("os30").textContent = data.ordens_30d ?? 0;

  const at = Array.isArray(data.atendimentos) ? data.atendimentos : [];
  $("atList").textContent = at.length
    ? at.map(a => `#${a.id} • Assunto ${a.assunto ?? a.id_assunto ?? "—"}`).join(" | ")
    : "Nenhum atendimento nos últimos 30 dias.";

  const os = Array.isArray(data.ordens) ? data.ordens : [];
  $("osList").textContent = os.length
    ? os.map(o => `#${o.id}`).join(" | ")
    : "Nenhuma O.S. nos últimos 30 dias.";
}

// ================= NOVO ATENDIMENTO =================
$("btnNovo").addEventListener("click", () => {
  $("novoBox").classList.toggle("hidden");
});

$("btnSalvarAtendimento").addEventListener("click", () => {
  const relatoCliente = $("relatoCliente").value.trim();
  const tratativaPadrao = $("tratativaPadrao").checked;
  const tratativaObs = $("tratativaObs").value.trim();

  if (!relatoCliente) {
    alert("Informe o relato do cliente.");
    return;
  }

  let tratativa = "";
  if (tratativaPadrao) {
    tratativa =
      "Realizada a tratativa padrão do suporte (limpeza de MAC, desconect, reboot ONU, " +
      "configurações do roteador dentro do padrão) e dispositivos reconectados à rede.";
  }

  if (tratativaObs) {
    tratativa += `\n\nObs: ${tratativaObs}`;
  }

  const textoFinal =
    `RELATO DO CLIENTE:
${relatoCliente}

TRATATIVA:
${tratativa || "—"}`;

  $("resultadoAtendimento").textContent =
    "Pronto para envio ao IXC (integração vem depois).";

  console.log("ATENDIMENTO GERADO:\n", textoFinal);
});





// ================= BUSCAR =================
async function buscar() {
  const q = $("login").value.trim();
  if (!q) return;

  msg("Buscando...");
  resetUI();

  const card = await apiGet(`/api/card/by-login?login=${encodeURIComponent(q)}`);
  fillCard(card);

  try {
    const summary = await apiGet(`/api/summary/by-login?login=${encodeURIComponent(q)}`);
    fillSummary(summary);
  } catch {
    $("atList").textContent = "Resumo indisponível.";
    $("osList").textContent = "Resumo indisponível.";
  }

  msg("OK");
}

// ================= EVENTS =================
$("btnBuscar").addEventListener("click", () =>
  buscar().catch(e => {
    msg("Erro");
    alert(e.message);
  })
);

$("login").addEventListener("keydown", (e) => {
  if (e.key === "Enter") buscar();
});

// ================= INIT =================
resetUI();


