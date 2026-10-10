(function () {
  "use strict";
  var GOODS = ["tea", "silk", "saffron"];
  var D = null, S = null;
  var state = { duel: null, step: 0, revealed: false, agent: "hollis", round: 1, coaches: 10, tau: 5, noise: "pilot", m: 16 };
  var $ = function (id) { return document.getElementById(id); };
  function el(tag, cls, html) { var e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function other(r) { return r === "first" ? "second" : "first"; }
  function fmt(x, d) { return Number(x).toFixed(d == null ? 2 : d); }
  function pct(x) { var v = 100 * x; return (v >= 99.5 && v < 100 ? ">99" : v < 1 && v > 0 ? "<1" : Math.round(v)) + "%"; }
  function num(x) { return Math.round(x).toLocaleString("en-US"); }
  function tokens(alloc, ghostStock) {
    var out = "";
    GOODS.forEach(function (g) {
      var n = alloc ? alloc[g] : 0;
      var row = "";
      for (var i = 0; i < n; i++) row += '<i class="tok ' + g + '"></i>';
      if (ghostStock) for (var j = n; j < ghostStock[g]; j++) row += '<i class="tok ghost"></i>';
      if (row) out += '<span class="tokens" title="' + n + " " + g + '">' + row + "</span>";
    });
    return out;
  }
  function goodsLine(alloc) {
    return GOODS.map(function (g) {
      var n = alloc[g], row = "";
      for (var i = 0; i < n; i++) row += '<i class="tok ' + g + '"></i>';
      return '<span class="good"><span class="tokens">' + (row || '<i class="tok ghost"></i>') + "</span>" + n + " " + g + "</span>";
    }).join("");
  }

  /* ---------- section 1: the score sheet ---------- */
  function duelById(id) { return D.duels.find(function (d) { return d.id === id; }); }
  function seriesLabel(d) { return d.eval ? "replay from an identical state" : d.series; }

  function tableAfter(d, k) { // open offer / agreement after action index k (0-based), -1 = before any
    var open = null, offers = {}, agreed = null;
    for (var i = 0; i <= k; i++) {
      var a = d.actions[i];
      if (!a.valid) continue;
      if (a.action === "offer") { offers[a.offer_id] = a; open = a; }
      else if (a.action === "reject") open = null;
      else if (a.action === "accept") { agreed = offers[a.offer_id]; open = null; }
    }
    return { open: open, agreed: agreed };
  }

  function renderSheet() {
    var d = state.duel, p = d.players;
    $("f-event").innerHTML = esc(d.id) + "<small>" + esc(seriesLabel(d)) + "</small>";
    $("f-scen").innerHTML = esc(d.scenario.id) + "<small>impasse " + d.scenario.impasse.first + " of 30</small>";
    $("f-first").innerHTML = esc(p.first.name) + "<small>memory v" + p.first.version + "</small>";
    $("f-second").innerHTML = esc(p.second.name) + "<small>memory v" + p.second.version + "</small>";
    $("stock").innerHTML = goodsLine(d.scenario.stock);
    var moves = $("moves");
    moves.innerHTML = '<div class="moves-head"><span class="label">No.</span><span class="label ink-first">' + esc(p.first.name) +
      '</span><span class="label ink-second">' + esc(p.second.name) + "</span></div>";
    for (var r = 0; r < 4; r++) {
      var row = el("div", "move-row");
      row.appendChild(el("div", "move-no", String(r + 1)));
      [0, 1].forEach(function (c) {
        var idx = r * 2 + c, a = d.actions[idx], role = c === 0 ? "first" : "second";
        var b = el("button", "cell " + role);
        b.type = "button";
        if (!a) { b.disabled = true; b.setAttribute("aria-label", "no action"); row.appendChild(b); return; }
        var html;
        if (!a.valid) html = '<span class="act invalid">Invalid, turn lost</span><span class="keeps">' + esc(a.error) + "</span>";
        else if (a.action === "offer") html = '<span class="act">Offer<span class="oid">' + a.offer_id + "</span></span>" + '<span class="keeps">keeps</span>' + '<span class="tray-goods">' + tokens(a.alloc[role]) + "</span>";
        else if (a.action === "accept") html = '<span class="act">Accepts<span class="oid">' + a.offer_id + '</span></span><span class="stamp">Deal</span>';
        else html = '<span class="act">Rejects<span class="oid">' + a.offer_id + "</span></span>";
        b.innerHTML = html;
        b.setAttribute("aria-label", "Move " + (idx + 1) + ", " + p[role].name + ": " + (a.valid ? a.action + " " + a.offer_id : "invalid"));
        if (idx === state.step) b.classList.add("is-current");
        if (idx > state.step) b.classList.add("is-future");
        b.addEventListener("click", function () { state.step = idx; renderSheet(); });
        row.appendChild(b);
      });
      moves.appendChild(row);
    }
    renderBoard();
    $("prev").disabled = state.step <= 0;
    $("next").disabled = state.step >= d.actions.length - 1;
    renderReveal();
  }

  function renderBoard() {
    var d = state.duel, a = d.actions[state.step], p = d.players, b = $("board");
    var t = tableAfter(d, state.step);
    var html = '<p class="says"><span class="says-who">Move ' + a.n + ", " + esc(p[a.role].name) + " says</span>&ldquo;" + esc(a.message) + "&rdquo;</p>";
    var shown = t.agreed || t.open;
    html += '<div class="tray"><p class="tray-title">' + (t.agreed ? "Agreed split, offer " + t.agreed.offer_id : t.open ? "Open offer " + t.open.offer_id + ", by " + esc(p[t.open.role].name) : "On the table") + "</p>";
    if (shown) {
      ["first", "second"].forEach(function (r) {
        html += '<div class="tray-side"><span class="who ink-' + r + '">' + esc(p[r].name) + '</span><span class="tray-goods">' + tokens(shown.alloc[r], null) + "</span></div>";
      });
    } else html += '<p class="empty-tray">Nothing is on the table.</p>';
    html += "</div>";
    if (state.step === d.actions.length - 1) {
      html += '<p class="decision">' + (d.status === "agreed" ? "Agreement after " + d.actions.length + " of 8 actions." : "No agreement after 8 actions: both sides get the impasse value.") + "</p>";
    }
    html += '<div class="seals">' + ["first", "second"].map(function (r) {
      return '<button type="button" class="seal' + (state.revealed ? " is-open" : "") + '" data-seal="1"><span class="ink-' + r + '">' + esc(p[r].name) + "&rsquo;s values</span><span class=\"wax\">" + (state.revealed ? "open" : "sealed") + "</span></button>";
    }).join("") + "</div>";
    b.innerHTML = html;
    b.querySelectorAll("[data-seal]").forEach(function (s) { s.addEventListener("click", function () { state.revealed = !state.revealed; renderBoard(); renderReveal(); if (state.revealed) $("reveal-panel").scrollIntoView({ behavior: "smooth", block: "nearest" }); }); });
  }

  function calcSide(d, r) {
    var vals = d.scenario.values[r];
    if (d.status === "agreed") {
      var parts = GOODS.filter(function (g) { return d.agreement[r][g] > 0; }).map(function (g) { return d.agreement[r][g] + " " + g + " &times; " + vals[g]; });
      return (parts.join(" + ") || "nothing") + " = " + d.values[r] + " of 30";
    }
    return "No deal: impasse value " + d.values[r] + " of 30";
  }

  function renderReveal() {
    var d = state.duel, panel = $("reveal-panel"), btn = $("reveal");
    btn.setAttribute("aria-expanded", state.revealed ? "true" : "false");
    btn.textContent = state.revealed ? "Seal the values again" : "Open the sealed values";
    panel.hidden = !state.revealed;
    if (!state.revealed) return;
    var html = "";
    ["first", "second"].forEach(function (r) {
      var v = d.scenario.values[r];
      html += '<div class="reveal-side"><h3 class="ink-' + r + '">' + esc(d.players[r].name) + "&rsquo;s hidden values</h3>";
      html += '<div class="values">' + GOODS.map(function (g) { return '<span><i class="tok ' + g + '"></i> ' + g + " " + v[g] + " each</span>"; }).join("") + "</div>";
      html += '<div class="calc">' + calcSide(d, r) + '<span class="total">' + fmt(d.scores[r]) + "</span></div></div>";
    });
    html += '<p class="rule-line">Score = value received &divide; value of the whole pool to that side (30). The engine computes it from the logged actions; the line above lets you check it by hand. Values were never shown to the other side.</p>';
    panel.innerHTML = html;
  }

  function loadDuel(id, toEnd) {
    state.duel = duelById(id);
    state.step = toEnd === false ? 0 : state.duel.actions.length - 1;
    state.revealed = false;
    renderSheet();
    document.querySelectorAll(".chip").forEach(function (c) { c.setAttribute("aria-pressed", c.dataset.id === id ? "true" : "false"); });
  }

  function renderCorpus() {
    $("corpus-count").textContent = "All " + D.duels.length + " recorded duels";
    var groups = [["series 1", "Series 1, before any coaching"], ["series 2", "Series 2, after the first round of notes"], ["series 3", "Series 3, after the second round"], ["calibration", "Replays from identical states (evaluation only, no memory writes)"]];
    var list = $("corpus-list");
    groups.forEach(function (g) {
      var box = el("div", "corpus-group");
      box.appendChild(el("h3", null, g[1]));
      var items = el("div", "corpus-items");
      D.duels.filter(function (d) { return d.series === g[0]; }).forEach(function (d) {
        var c = el("button", "chip", esc(d.id) + " " + esc(d.players.first.name) + " v " + esc(d.players.second.name) + " " + fmt(d.scores.first) + "/" + fmt(d.scores.second));
        c.type = "button"; c.dataset.id = d.id;
        c.addEventListener("click", function () { loadDuel(d.id); $("sheet").scrollIntoView({ behavior: "smooth", block: "start" }); });
        items.appendChild(c);
      });
      box.appendChild(items);
      list.appendChild(box);
    });
  }

  /* ---------- section 2: coaching chain ---------- */
  function agentById(id) { return D.agents.find(function (a) { return a.id === id; }); }
  function segButtons(container, items, current, onPick) {
    container.innerHTML = "";
    items.forEach(function (it) {
      var b = el("button", null, it.html);
      b.type = "button"; b.setAttribute("role", "tab");
      b.setAttribute("aria-selected", String(it.value) === String(current) ? "true" : "false");
      b.addEventListener("click", function () { onPick(it.value); });
      container.appendChild(b);
    });
  }
  var LEARN = { coached: "coached", self: "self-reflective", none: "never learns" };

  function renderChain() {
    segButtons($("agent-tabs"), D.agents.map(function (a) { return { value: a.id, html: esc(a.name) + '<span class="sub">' + LEARN[a.learning] + "</span>" }; }), state.agent, function (v) { state.agent = v; renderChain(); });
    var ag = agentById(state.agent);
    var roundsEl = $("round-tabs");
    if (ag.learning === "none") { roundsEl.hidden = true; }
    else {
      roundsEl.hidden = false;
      segButtons(roundsEl, [{ value: 1, html: "After series 1" }, { value: 2, html: "After series 2" }], state.round, function (v) { state.round = v; renderChain(); });
    }
    var chain = $("chain");
    if (ag.learning === "none") {
      var n = D.duels.filter(function (d) { return d.players.first.agent === ag.id || d.players.second.agent === ag.id; }).length;
      chain.innerHTML = '<div><div class="note-card"><span class="by-stamp">Never learns</span><p class="from">No note, no reflection</p><blockquote>' + esc(ag.name) + " is the copy that never learns. It played " + n + " duels with the same four starting lessons.</blockquote></div>" +
        '<p class="arrow-step">Why it is here</p><p class="lesson">A copy that does not learn shows how much of any change comes from the opponents and scenarios rather than from memory.</p></div>' +
        ledger(ag.name, 1, 1, ag.lessons, ag.lessons, null, null) ;
      return;
    }
    var ev = D.memory_events.find(function (e) { return e.agent === ag.id && e.round === state.round; });
    var left = "";
    if (ev.source === "coach") {
      left += '<div class="note-card"><span class="by-stamp">Demo coach<br>The AI Pipe</span><p class="from">Coach&rsquo;s note after series ' + state.round + ", written by The AI Pipe for this demo</p><blockquote>" + esc(ev.feedback) + "</blockquote></div>";
      left += '<p class="arrow-step">The lesson ' + esc(ag.name) + " wrote from the note</p>";
    } else {
      left += '<div class="note-card"><span class="by-stamp">No coach</span><p class="from">No coach. Same match information, including the other side&rsquo;s revealed values</p><blockquote>' + esc(ag.name) + " reviewed its own series " + state.round + " duels and wrote its own lesson.</blockquote></div>";
      left += '<p class="arrow-step">The lesson ' + esc(ag.name) + " wrote for itself</p>";
    }
    left += '<p class="lesson">' + esc(ev.lesson) + "</p>";
    var dec = ev.decision === "add" ? "Added to a free slot" : ev.decision === "replace" ? "Replaced slot " + ev.slot + " (memory was full)" : "Discarded; memory kept as it was";
    left += '<p class="decision"><b>' + dec + ".</b> " + (ev.reason ? "Its reason: " + esc(ev.reason) : "") + "</p>";
    var nextSeries = "series " + (state.round + 1);
    var next = D.duels.find(function (d) { return d.series === nextSeries && (d.players.first.agent === ag.id || d.players.second.agent === ag.id); });
    chain.innerHTML = "<div>" + left + "</div>" + ledger(ag.name, ev.before_version, ev.after_version, ev.before, ev.after, ev, next);
    var btn = chain.querySelector("[data-open]");
    if (btn) btn.addEventListener("click", function () { loadDuel(btn.dataset.open, false); $("sheet").scrollIntoView({ behavior: "smooth", block: "start" }); });
  }

  function ledger(name, vb, va, before, after, ev, next) {
    var html = '<div class="ledger"><div class="ledger-head"><span class="title">' + esc(name) + "&rsquo;s memory</span><span class=\"label\">" + (vb === va ? "version " + va : "version " + vb + " to " + va) + ", " + after.length + " of 5 slots</span></div><ol>";
    for (var i = 0; i < 5; i++) {
      var line = after[i];
      if (line == null) { html += '<li class="is-empty">empty slot</li>'; continue; }
      var isNew = ev && ev.valid && ev.decision !== "discard" && ((ev.decision === "add" && i === after.length - 1) || (ev.decision === "replace" && ev.slot === i + 1));
      html += "<li" + (isNew ? ' class="is-new"' : "") + "><span>" + (isNew && ev.evicted ? '<span class="evicted">' + esc(ev.evicted) + "</span>" : "") + esc(line) + "</span></li>";
    }
    html += "</ol>";
    if (next) {
      var role = next.players.first.agent === ev.agent ? "first" : "second";
      var loaded = JSON.stringify(next.players[role].lessons) === JSON.stringify(after);
      html += '<div class="ledger-foot"><span>Loaded into ' + esc(next.id) + " against " + esc(next.players[other(role)].name) + ", memory v" + next.players[role].version + ". " +
        (loaded ? '<span class="loaded">Matches the memory logged with this duel</span>' : "") + '</span><button type="button" class="btn" data-open="' + esc(next.id) + '">Open ' + esc(next.id) + " on the sheet</button></div>";
    }
    return html + "</div>";
  }

  /* ---------- section 3: what a pilot could detect ---------- */
  var MS = [4, 8, 16, 32, 64];
  function cell(mu, m) {
    return S.cells.find(function (c) { return c.coaches === state.coaches && c.mu === mu && c.tau === state.tau && c.noise === state.noise && c.eval_matches === m; });
  }
  function renderControls() {
    segButtons($("c-coaches"), [8, 10, 16].map(function (n) { return { value: n, html: String(n) }; }), state.coaches, function (v) { state.coaches = v; renderPower(); });
    segButtons($("c-tau"), [{ value: 0, html: "none" }, { value: 5, html: "&plusmn;5 points" }, { value: 10, html: "&plusmn;10 points" }], state.tau, function (v) { state.tau = v; renderPower(); });
    segButtons($("c-noise"), [{ value: "low", html: "half" }, { value: "pilot", html: "as measured" }, { value: "high", html: "1.5&times;" }], state.noise, function (v) { state.noise = v; renderPower(); });
  }
  function renderChart() {
    var svg = $("chart"), cw = svg.parentNode.clientWidth || 640;
    var narrow = cw < 520;
    var W = Math.round(Math.max(340, Math.min(700, cw))), H = narrow ? 340 : 400, L = narrow ? 44 : 54, R = narrow ? 74 : 132, T = 48, B = 34;
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    var colW = (W - L - R) / MS.length;
    var cx = function (i) { return L + colW * (i + 0.5); };
    var y = function (v) { return T + (1 - v) * (H - T - B); };
    var g = '<desc id="chart-desc">Share of simulated pilots that detect a coaching benefit, for each number of evaluation matches per frozen version</desc>';
    var cur = MS.indexOf(state.m);
    g += '<rect class="col-current" x="' + (L + colW * cur) + '" y="0" width="' + colW + '" height="' + H + '"/>';
    [0, 0.2, 0.4, 0.6, 0.8, 1].forEach(function (v) {
      g += '<line class="rule" x1="' + L + '" x2="' + (W - R) + '" y1="' + y(v) + '" y2="' + y(v) + '"/>';
      g += '<text class="tick" x="' + (L - 8) + '" y="' + (y(v) + 4) + '" text-anchor="end">' + Math.round(v * 100) + "%</text>";
    });
    MS.forEach(function (m, i) {
      if (i > 0) g += '<line class="col-rule" x1="' + (L + colW * i) + '" x2="' + (L + colW * i) + '" y1="0" y2="' + H + '"/>';
      g += '<text class="colno' + (i === cur ? " is-current" : "") + '" x="' + cx(i) + '" y="30" text-anchor="middle">' + m + "</text>";
    });
    g += '<line class="col-rule" x1="' + L + '" x2="' + L + '" y1="0" y2="' + H + '"/>';
    g += '<line class="col-rule" x1="' + (W - R) + '" x2="' + (W - R) + '" y1="0" y2="' + H + '"/>';
    g += '<line class="frame" x1="0" x2="' + W + '" y1="' + (T - 8) + '" y2="' + (T - 8) + '"/>';
    g += '<text class="axis-title" x="' + ((L + W - R) / 2) + '" y="' + (H - 10) + '" text-anchor="middle">evaluation matches per frozen version, choose a column</text>';
    var series = [[10, "l10", "pt10", narrow ? "+10" : "+10 points"], [5, "l5", "pt5", narrow ? "+5" : "+5 points"], [0, "l0", "pt0", narrow ? "none" : "no benefit"]];
    var ends = [];
    series.forEach(function (s) {
      var pts = MS.map(function (m, i) { return [cx(i), y(cell(s[0], m).reject_rate)]; });
      g += '<polyline class="line ' + s[1] + '" points="' + pts.map(function (p) { return p.join(","); }).join(" ") + '"/>';
      pts.forEach(function (p, i) {
        var sz = i === cur ? 10 : 7;
        g += '<rect class="' + s[2] + '" x="' + (p[0] - sz / 2) + '" y="' + (p[1] - sz / 2) + '" width="' + sz + '" height="' + sz + '" rx="1.5"/>';
        if (i === cur) g += '<ellipse class="pencil-ring" cx="' + p[0] + '" cy="' + p[1] + '" rx="13" ry="10" transform="rotate(-12 ' + p[0] + " " + p[1] + ')"/>';
      });
      ends.push({ y: pts[pts.length - 1][1], cls: s[2], text: s[3] });
    });
    ends.sort(function (a, b) { return a.y - b.y; });
    for (var i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 20) ends[i].y = ends[i - 1].y + 20;
    ends.forEach(function (e) { g += '<text class="lab ' + e.cls + '" x="' + (W - R + 10) + '" y="' + (e.y + 5) + '">' + e.text + "</text>"; });
    MS.forEach(function (m, i) {
      g += '<rect data-m="' + m + '" x="' + (L + colW * i) + '" y="0" width="' + colW + '" height="' + H + '" fill="transparent" style="cursor:pointer"><title>' + m + " evaluation matches</title></rect>";
    });
    svg.innerHTML = g;
    svg.querySelectorAll("rect[data-m]").forEach(function (r) { r.addEventListener("click", function () { state.m = +r.dataset.m; renderPower(); }); });
  }
  function totalMatches(n, m) { var p = S.params; return n * 2 * p.train_matches_per_day * p.days + n * m * 7; }
  function renderPower() {
    renderControls();
    renderChart();
    var c10 = cell(10, state.m), c5 = cell(5, state.m), c0 = cell(0, state.m);
    $("readout").innerHTML = "With <b>" + state.coaches + " coaches</b> and <b>" + state.m + " evaluation matches</b> per frozen version, the 95% interval on the average benefit is about <b>&plusmn;" + fmt(c5.ci_width / 2, 1) +
      " points</b>. A point is one percent of the pool&rsquo;s value to the agent. The figures below are the share of " + num(S.reps) + " simulated pilots in which the test finds a benefit.";
    $("tally-foot").innerHTML = [[c10, "pt10", "ink-first", "+10 point benefit"], [c5, "pt5", "ink-second", "+5 point benefit"], [c0, "pt0", "", "no benefit (false alarms)"]].map(function (x) {
      return '<div class="tally-cell"><span class="who ' + x[2] + '">' + x[3] + '</span><span class="fig">' + (x[0] === c0 ? fmt(100 * c0.reject_rate, 1) + "%" : pct(x[0].reject_rate)) + "</span></div>";
    }).join("") + '<div class="tally-stamp"><span class="stamp">at ' + state.m + " matches</span></div>";
    var rs = S.rank_stability.find(function (r) { return r.coaches === state.coaches && r.eval_matches === state.m; });
    $("rank-line").innerHTML = "Ranking the " + rs.versions + " frozen versions is shakier. If agents truly differ by about " + fmt(D.pilot.agent_mean_sd_points, 1) + " points, two runs of the same " + state.m + "-match evaluation would agree with a median rank correlation of " + fmt(rs.spearman_median) +
      ". That spread is a hypothesis: shuffling the agent labels of the demo season gives one at least as large " + Math.round(100 * D.pilot.agent_spread_perm_p) + "% of the time (p = " + fmt(D.pilot.agent_spread_perm_p) + "), so it may be noise alone.";
    renderCost();
  }
  function renderCost() {
    var c = D.cost, t = c.per_duel_tokens, n = state.coaches, m = state.m;
    var matches = totalMatches(n, m), updates = n * 2 * S.params.days;
    var perUpdate = c.learning.equivalent_usd / c.learning.calls;
    var usd = matches * c.per_duel_usd + updates * perUpdate;
    var calls = c.duel_only.calls + c.learning.calls;
    $("cost").innerHTML =
      '<div class="cost-line"><span class="k">Spent on model APIs for this demo</span><span class="v"><b>$0.</b> All ' + calls + " model calls ran on a Claude subscription through the Claude Code CLI, from an empty folder, with no tools, no settings files and no API key in the environment.</span></div>" +
      '<div class="cost-line"><span class="k">Observed usage</span><span class="v">Per duel on average: <b>' + num(t.output) + "</b> output tokens, <b>" + num(t.cache_write_1h + t.cache_write_5m) + "</b> input tokens written to cache and <b>" + num(t.cache_read) + "</b> read from it, over " + fmt(c.duel_only.calls / c.duels, 1) + " calls and about " + Math.round(c.per_duel_seconds) + " seconds. " + c.lesson_updates + " lesson updates added " + num(c.learning.tokens.output) + " output tokens in all. " + (c.incidents ? c.incidents + " execution incidents." : "No failed call, no invalid action, no impasse.") + "</span></div>" +
      '<div class="cost-line"><span class="k">Equivalent at the public API price</span><span class="v"><b>$' + fmt(c.per_duel_usd, 3) + "</b> per duel, <b>$" + fmt(c.per_duel_with_learning_usd, 3) + "</b> counting lesson updates, at the list price of " + esc(c.model) + ' read on ' + esc(c.price_date) + ' (<a href="' + esc(c.price_source) + '">source</a>), low effort setting. At that rate the pilot selected above, about <b>' + num(matches) + "</b> matches and " + num(updates) + " lesson updates, would come to about <b>$" + Math.round(usd) + "</b>.</span></div>";
  }
  function renderAssumptions() {
    var p = D.pilot, s = S.params;
    $("assumptions").innerHTML = "<ul>" +
      "<li>Replay noise: " + fmt(p.replay_sd_points, 1) + " points, measured on " + p.replays + " replays from " + p.calibration.length + " identical starting states (same personalities, memories, scenario, values and roles). It measures variability within one situation, not between coaches. Shown halved and multiplied by 1.5.</li>" +
      "<li>First-mover edge: " + fmt(p.first_mover_edge_points, 1) + " points, measured over " + p.duels + " season duels; balanced by playing both roles.</li>" +
      "<li>Spread between scenarios: " + fmt(p.scenario_sd_points, 1) + " points. Spread between agents: " + fmt(p.agent_mean_sd_points, 1) + " points, used as a hypothesis only: with four agents, a label permutation gives a spread at least this large with p = " + fmt(p.agent_spread_perm_p) + ".</li>" +
      "<li>Impasses: " + Math.round(p.impasse_rate * p.duels) + " of " + p.duels + " season duels; simulated at that rate.</li>" +
      "<li>Gain from self-reflection alone: +" + s.self_gain_mean + " &plusmn; " + s.self_gain_sd + " points, assumed. It cancels in the comparison.</li>" +
      "<li>Average benefit of coaching (0, +5, +10 points) and how much it varies between coaches (none, &plusmn;5, &plusmn;10): hypotheses, not measurements.</li>" +
      "<li>Schedule: " + s.train_matches_per_day + " training matches per learning branch per day for " + s.days + " days, one lesson update per day; evaluations at the start, day 7 and day 14 against a frozen panel on held-out scenarios, with no memory writes.</li>" +
      "<li>Analysis: for each coach, coached minus self-reflective score on the same evaluation matches; two-sided t-test across coaches at 5%. " + num(S.reps) + " simulated pilots per setting, fixed seed.</li></ul>";
  }

  /* ---------- wiring ---------- */
  function init() {
    renderCorpus();
    loadDuel(D.featured);
    $("prev").addEventListener("click", function () { if (state.step > 0) { state.step--; renderSheet(); } });
    $("next").addEventListener("click", function () { if (state.step < state.duel.actions.length - 1) { state.step++; renderSheet(); } });
    $("reveal").addEventListener("click", function () { state.revealed = !state.revealed; renderBoard(); renderReveal(); });
    renderChain();
    renderPower();
    renderAssumptions();
    var lastW = window.innerWidth;
    window.addEventListener("resize", function () { if (Math.abs(window.innerWidth - lastW) > 40) { lastW = window.innerWidth; renderChart(); } });
  }
  Promise.all([fetch("data/corpus.json").then(function (r) { return r.json(); }), fetch("data/sim.json").then(function (r) { return r.json(); })])
    .then(function (res) { D = res[0]; S = res[1]; init(); })
    .catch(function (e) { document.querySelector("main").insertAdjacentHTML("afterbegin", '<p style="color:#B2352B">The recorded data could not be loaded: ' + esc(e.message) + "</p>"); });
})();
