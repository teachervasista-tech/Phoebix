const INR = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 });
const today = new Date();
const isoDate = (date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
const defaultBank = { accountHolder: "", bankName: "", branch: "", accountNumber: "", ifsc: "", accountType: "Current", upiId: "" };
const defaultStore = { name: "Phoebix Pharmacy", branch: "Store 01", address: "", city: "", state: "", pincode: "", phone: "", gstin: "", drugLicense: "", invoicePrefix: "INV", bank: defaultBank };
const defaultRules = { earnPer: 100, pointsPerRupee: 1, redeemMaxPercent: 20, birthday: true, wellness: true, refill: false };

function normalizeProduct(product) {
  const batches = (Array.isArray(product.batches) ? product.batches : [{
    id: `${product.id}-batch-1`,
    batch: product.batch,
    expiry: product.expiry,
    stock: product.stock
  }]).map((batch, index) => ({
    id: batch.id || `${product.id}-batch-${index + 1}`,
    batch: String(batch.batch || ""),
    expiry: batch.expiry,
    stock: Math.max(0, Number(batch.stock) || 0)
  }));
  return { ...product, batches, stock: batches.reduce((sum, batch) => sum + batch.stock, 0), batch: batches[0]?.batch || "", expiry: batches[0]?.expiry || "" };
}

function normalizeState(parsed) {
  if (!parsed || !Array.isArray(parsed.products) || !Array.isArray(parsed.customers) || !Array.isArray(parsed.transactions)) throw new Error("Saved pharmacy data has an unexpected format.");
  return {
    ...parsed,
    products: parsed.products.map(normalizeProduct),
    offers: Array.isArray(parsed.offers) ? parsed.offers : [],
    store: { ...defaultStore, ...parsed.store, bank: { ...defaultBank, ...parsed.store?.bank } },
    rules: { ...defaultRules, ...parsed.rules }
  };
}

let state = null;
let activePage = "dashboard";
let cart = [];
let posCategory = "All items";
let posSearch = "";
let inventoryFilter = "All products";
let customerFilter = "";
let customerTierFilter = "All members";
let selectedCustomer = "";
let invoiceSequence = 1049;
let discountInput = 0;
let discountType = "percent";
let redeemInput = 0;
let selectedOfferId = "";
let paymentMethod = "Cash";
let phonepeConfigured = false;
let databaseRevision = 0;
let databaseReady = false;
let pendingDatabaseSaves = 0;
let databaseSaveChain = Promise.resolve();
let currentUser = null;
let usersList = [];

const nativeFetch = window.fetch.bind(window);
window.fetch = async (...args) => {
  const response = await nativeFetch(...args);
  if (response.status === 401 && !String(args[0]).startsWith("/api/auth/")) handleSessionExpired();
  return response;
};

async function sendJSON(url, method, body) {
  let response;
  try {
    response = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}), cache: "no-store" });
  } catch {
    throw new Error("Cannot reach the Phoebix server. Make sure it is running.");
  }
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || `Request failed (HTTP ${response.status}).`);
  return result;
}
const content = document.getElementById("app-content");
const modalRoot = document.getElementById("modal-root");
const databaseStatus = document.getElementById("database-status");
const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
const money = (value) => INR.format(Number(value) || 0);
const fmtDate = (date) => new Date(`${date}T00:00:00`).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
const productById = (id) => state.products.find((product) => product.id === id);
const customerById = (id) => state.customers.find((customer) => customer.id === id);
const batchById = (product, batchId) => product?.batches.find((batch) => batch.id === batchId);
const syncProductStock = (product) => {
  product.stock = product.batches.reduce((sum, batch) => sum + batch.stock, 0);
  product.batch = product.batches[0]?.batch || "";
  product.expiry = product.batches[0]?.expiry || "";
};
function setDatabaseStatus(status, message) {
  databaseStatus.className = `database-status ${status}`;
  databaseStatus.title = message;
  databaseStatus.querySelector("span").textContent = ({
    connecting: "Connecting",
    connected: "SQLite saved",
    saving: "Saving",
    offline: "Database unavailable",
    error: "Save failed",
    conflict: "Reload required"
  })[status];
}

async function writeStateToDatabase(snapshot, expectedRevision) {
  const response = await fetch("/api/state", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ state: snapshot, expectedRevision }),
    cache: "no-store"
  });
  const responseBody = await response.text();
  let result;
  try {
    result = JSON.parse(responseBody);
  } catch {
    throw new Error(`Database API returned an invalid response (HTTP ${response.status}). Start Phoebix with start_phoebix.bat.`);
  }
  if (response.status === 409) {
    const error = new Error(result.error || "The database was changed by another client.");
    error.code = "conflict";
    throw error;
  }
  if (!response.ok) throw new Error(result.error || `Database save failed (${response.status}).`);
  databaseRevision = result.revision;
}

function queueDatabaseSave() {
  if (!databaseReady) return;
  pendingDatabaseSaves += 1;
  document.querySelector(".app-shell").inert = true;
  setDatabaseStatus("saving", "Saving changes to the Phoebix SQLite database");
  const snapshot = structuredClone(state);
  databaseSaveChain = databaseSaveChain.catch(() => {}).then(async () => {
    if (!databaseReady) return;
    try {
      await writeStateToDatabase(snapshot, databaseRevision);
      pendingDatabaseSaves -= 1;
      if (pendingDatabaseSaves === 0) {
        setDatabaseStatus("connected", "Your changes are saved in the Phoebix SQLite database");
        document.querySelector(".app-shell").inert = false;
      }
    } catch (error) {
      console.error("Could not save pharmacy data to the backend database.", error);
      databaseReady = false;
      setDatabaseStatus(error.code === "conflict" ? "conflict" : "error", error.message);
      toast(error.code === "conflict"
        ? "Database changed elsewhere. Reload to restore the latest saved data."
        : `Database save failed: ${error.message}`);
    }
  });
}

function persist() {
  queueDatabaseSave();
}

async function initializeDatabase() {
  setDatabaseStatus("connecting", "Connecting to the Phoebix SQLite database");
  try {
    const response = await fetch("/api/state", { cache: "no-store" });
    if (!response.ok) throw new Error(`Database API returned ${response.status}.`);
    const result = await response.json();
    if (!result.state) throw new Error("The SQLite workspace is empty. Restart Phoebix to initialize its sample database.");
    databaseRevision = result.revision;
    state = normalizeState(result.state);
    invoiceSequence = state.transactions.reduce((highest, transaction) => {
      const number = Number(transaction.id.match(/\d+$/)?.[0] || 0);
      return Math.max(highest, number);
    }, 1048) + 1;
    const paymentConfigResponse = await fetch("/api/payments/phonepe/config", { cache: "no-store" });
    if (!paymentConfigResponse.ok) throw new Error(`Payment configuration API returned ${paymentConfigResponse.status}.`);
    const paymentConfig = await paymentConfigResponse.json();
    phonepeConfigured = Boolean(paymentConfig.configured);
    databaseReady = true;
    setDatabaseStatus("connected", "Connected to the Phoebix SQLite database");
  } catch (error) {
    console.error("Could not connect to the Phoebix backend database.", error);
    databaseReady = false;
    setDatabaseStatus("offline", "Backend unavailable; the workspace is locked until SQLite can be reached");
    toast("Backend database unavailable. Phoebix requires a database connection; start server.py and reload.");
    return;
  }
  document.querySelector(".app-shell").inert = false;
  render();
  await processPhonePeReturn();
}

document.querySelector(".app-shell").inert = true;
const loginRoot = document.getElementById("login-root");

function showLogin(message = "") {
  document.querySelector(".app-shell").inert = true;
  modalRoot.innerHTML = "";
  loginRoot.innerHTML = `<div class="login-screen"><form class="login-card" id="login-form">
    <div class="brand"><span class="brand-mark"><svg viewBox="0 0 32 32" aria-hidden="true"><path d="M13.5 4h5v9h9v5h-9v9h-5v-9h-9v-5h9z"/></svg></span><span><strong>Phoebix</strong><small>PHARMACY OS</small></span></div>
    <h1>Sign in</h1><p>Use your Phoebix login ID. Every sale is recorded against it.</p>
    ${message ? `<div class="login-error" role="alert">${escapeHTML(message)}</div>` : ""}
    <div class="form-field"><label for="login-username">Login ID</label><input id="login-username" name="username" autocomplete="username" autocapitalize="none" required></div>
    <div class="form-field"><label for="login-password">Password</label><input id="login-password" name="password" type="password" autocomplete="current-password" required></div>
    <button class="button button-primary" type="submit">Sign in</button>
  </form></div>`;
  const form = loginRoot.querySelector("#login-form");
  loginRoot.querySelector("#login-username").focus();
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = form.querySelector("button");
    submit.disabled = true;
    try {
      const result = await sendJSON("/api/auth/login", "POST", { username: form.username.value, password: form.password.value });
      currentUser = result.user;
      loginRoot.innerHTML = "";
      onSignedIn();
    } catch (error) {
      showLogin(error.message);
    }
  });
}

function handleSessionExpired() {
  if (!currentUser) return;
  currentUser = null;
  databaseReady = false;
  showLogin("Your session ended. Sign in again to continue.");
}

function onSignedInChrome() {
  document.getElementById("profile-name").textContent = currentUser.name;
  document.getElementById("profile-avatar").textContent = initialsFor(currentUser.name);
  document.getElementById("top-avatar").textContent = initialsFor(currentUser.name);
}

function onSignedIn() {
  const isAdmin = currentUser.role === "admin";
  onSignedInChrome();
  document.getElementById("profile-role").textContent = `${isAdmin ? "Administrator" : "Staff"} · @${currentUser.username}`;
  document.getElementById("nav-users").hidden = !isAdmin;
  activePage = "dashboard";
  document.querySelectorAll(".nav-link[data-page]").forEach((link) => link.classList.toggle("active", link.dataset.page === "dashboard"));
  document.getElementById("page-crumb").textContent = "Overview";
  if (currentUser.mustChangePassword) showChangePassword(true);
  else initializeDatabase();
}

async function signOut() {
  await databaseSaveChain.catch(() => {});
  try { await sendJSON("/api/auth/logout", "POST"); } catch { /* the cookie is cleared on the next sign-in */ }
  currentUser = null;
  databaseReady = false;
  state = null;
  cart = [];
  selectedCustomer = "";
  usersList = [];
  content.innerHTML = "";
  showLogin();
}

function showChangePassword(forced = false) {
  openModal(forced ? "Choose a new password" : "Account", forced ? "You are using a temporary password. Set your own to continue." : `Signed in as ${escapeHTML(currentUser.name)} (@${escapeHTML(currentUser.username)}).`, `<div class="form-grid">
    <div class="form-field full"><label for="pw-current">Current password</label><input id="pw-current" name="currentPassword" type="password" autocomplete="current-password" required></div>
    <div class="form-field"><label for="pw-new">New password (8+ characters)</label><input id="pw-new" name="newPassword" type="password" autocomplete="new-password" minlength="8" required></div>
    <div class="form-field"><label for="pw-confirm">Confirm new password</label><input id="pw-confirm" name="confirmPassword" type="password" autocomplete="new-password" minlength="8" required></div>
    <div class="form-field full"><button type="button" class="button" data-action="logout">Sign out</button></div>
  </div>`, "Change password", async (data) => {
    if (data.newPassword !== data.confirmPassword) return toast("The new passwords do not match.");
    try {
      const result = await sendJSON("/api/auth/password", "POST", { currentPassword: data.currentPassword, newPassword: data.newPassword });
      currentUser = result.user;
      modalRoot.innerHTML = "";
      toast("Password changed.");
      if (!databaseReady) initializeDatabase();
    } catch (error) {
      toast(error.message);
    }
  });
  if (forced) {
    const modal = modalRoot.querySelector(".modal");
    modal.classList.add("modal-locked");
    modal.querySelector(".modal-actions [data-action=close-modal]").remove();
  }
}

const roleLabel = (role) => (role === "admin" ? "Administrator" : "Staff");
const soldByLabel = (transaction) => (transaction.soldBy ? `${escapeHTML(transaction.soldBy.name)}<div class="sub-cell">@${escapeHTML(transaction.soldBy.username)}</div>` : "—");

async function loadUsers() {
  try {
    const response = await fetch("/api/users", { cache: "no-store" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Could not load users.");
    usersList = result.users;
    if (activePage === "users") renderUsers();
  } catch (error) {
    toast(error.message);
  }
}

function renderUsers() {
  content.innerHTML = `${pageHeading("Users & access", "Everyone who signs in gets their own login ID, and every sale is recorded against it.", `<button class="button button-primary" data-action="add-user"><span class="plus">+</span> Add user</button>`)}
    <section class="panel table-panel"><div class="table-wrap"><table><thead><tr><th>NAME</th><th>LOGIN ID</th><th>ROLE</th><th>STATUS</th><th>LAST SIGN-IN</th><th></th></tr></thead><tbody>${usersList.map((user) => `<tr><td class="strong-cell">${escapeHTML(user.name)}</td><td>@${escapeHTML(user.username)}</td><td>${roleLabel(user.role)}</td><td><span class="status-pill ${user.active ? "status-paid" : "status-credit"}">${user.active ? (user.mustChangePassword ? "Temporary password" : "Active") : "Disabled"}</span></td><td>${user.lastLoginAt ? new Date(user.lastLoginAt).toLocaleString("en-IN") : "Never"}</td><td><button class="inline-link" data-action="edit-user" data-id="${escapeHTML(user.id)}">Edit</button></td></tr>`).join("") || `<tr><td colspan="6">Loading users…</td></tr>`}</tbody></table></div></section>`;
}

function showAddUser() {
  openModal("Add a user", "They must choose their own password the first time they sign in.", `<div class="form-grid">
    <div class="form-field"><label for="u-name">Full name</label><input id="u-name" name="name" required></div>
    <div class="form-field"><label for="u-username">Login ID</label><input id="u-username" name="username" autocapitalize="none" pattern="[A-Za-z0-9._\\-]{3,32}" title="3-32 letters, digits, dot, dash or underscore" required></div>
    <div class="form-field"><label for="u-role">Role</label><select id="u-role" name="role"><option value="staff">Staff</option><option value="admin">Administrator</option></select></div>
    <div class="form-field"><label for="u-password">Temporary password</label><input id="u-password" name="password" type="text" minlength="8" autocomplete="off" required></div>
  </div>`, "Add user", async (data) => {
    try {
      await sendJSON("/api/users", "POST", data);
      modalRoot.innerHTML = "";
      toast("User created.");
      loadUsers();
    } catch (error) {
      toast(error.message);
    }
  });
}

function showEditUser(id) {
  const user = usersList.find((entry) => entry.id === id);
  if (!user) return;
  const isSelf = user.id === currentUser.id;
  openModal(`Edit @${escapeHTML(user.username)}`, "Changing the role, disabling the account or resetting the password signs the user out.", `<div class="form-grid">
    <div class="form-field full"><label for="e-name">Full name</label><input id="e-name" name="name" value="${escapeHTML(user.name)}" required></div>
    <div class="form-field"><label for="e-role">Role</label><select id="e-role" name="role" ${isSelf ? "disabled" : ""}><option value="staff" ${user.role === "staff" ? "selected" : ""}>Staff</option><option value="admin" ${user.role === "admin" ? "selected" : ""}>Administrator</option></select></div>
    <div class="form-field"><label for="e-active">Status</label><select id="e-active" name="active" ${isSelf ? "disabled" : ""}><option value="true" ${user.active ? "selected" : ""}>Active</option><option value="false" ${user.active ? "" : "selected"}>Disabled</option></select></div>
    <div class="form-field full"><label for="e-password">Reset password (optional temporary password)</label><input id="e-password" name="newPassword" type="text" minlength="8" autocomplete="off" placeholder="Leave blank to keep the current password"></div>
  </div>`, "Save user", async (data) => {
    const body = { name: data.name };
    if (!isSelf) { body.role = data.role; body.active = data.active === "true"; }
    if (data.newPassword) body.newPassword = data.newPassword;
    try {
      const result = await sendJSON(`/api/users/${encodeURIComponent(id)}`, "PUT", body);
      if (isSelf) { currentUser = { ...currentUser, name: result.user.name }; onSignedInChrome(); }
      modalRoot.innerHTML = "";
      toast("User updated.");
      loadUsers();
    } catch (error) {
      toast(error.message);
    }
  });
}

async function bootstrapSession() {
  setDatabaseStatus("connecting", "Connecting to the Phoebix SQLite database");
  let databaseUp = false;
  try {
    const health = await nativeFetch("/api/health", { cache: "no-store" });
    databaseUp = health.ok;
  } catch { /* reported below */ }
  if (!databaseUp) {
    setDatabaseStatus("offline", "Backend unavailable; the workspace is locked until SQLite can be reached");
    showLogin("The Phoebix database is not reachable. Close Phoebix completely and start it again.");
    return;
  }
  setDatabaseStatus("connected", "Connected to the Phoebix SQLite database");
  try {
    const response = await nativeFetch("/api/auth/session", { cache: "no-store" });
    if (response.ok) {
      currentUser = (await response.json()).user;
      onSignedIn();
      return;
    }
  } catch { /* the sign-in form reports connection problems */ }
  showLogin();
}
const initialsFor = (name) => name.split(/\s+/).slice(0, 2).map((part) => part[0] || "").join("").toUpperCase();
const escapeDateDays = (date) => Math.ceil((new Date(`${date}T00:00:00`) - new Date(`${isoDate(new Date())}T00:00:00`)) / 86400000);
const isLowStock = (product) => product.stock <= product.reorder;
const isExpired = (batch) => escapeDateDays(batch.expiry) < 0;
const isNearExpiry = (product) => product.batches.some((batch) => batch.stock > 0 && escapeDateDays(batch.expiry) <= 90);
const hasSellableStock = (product) => product.batches.some((batch) => batch.stock > 0 && !isExpired(batch));

function toast(message) {
  const region = document.getElementById("toast-region");
  const element = document.createElement("div");
  element.className = "toast";
  element.textContent = message;
  region.append(element);
  setTimeout(() => element.remove(), 3000);
}

function setPage(page) {
  activePage = page;
  document.querySelectorAll(".nav-link[data-page]").forEach((link) => link.classList.toggle("active", link.dataset.page === page));
  document.getElementById("page-crumb").textContent = ({ dashboard: "Overview", sales: "Point of sale", inventory: "Inventory", customers: "Customers",   rewards: "Rewards & offers", reports: "Reports", users: "Users & access" })[page] || "Overview"; 
  document.getElementById("sidebar").classList.remove("open");
  render();
    if (page === "users") loadUsers();
}

function pageHeading(title, subtitle, action = "") {
  return `<div class="page-heading"><div><p class="eyebrow">${escapeHTML(state.store.name.toUpperCase())} · ${escapeHTML(state.store.city.toUpperCase())}</p><h1>${title}</h1><p class="heading-subtitle">${subtitle}</p></div><div class="heading-actions">${action}</div></div>`;
}

function metricCard(label, value, icon, tone, foot) {
  return `<div class="metric-card"><div class="metric-top">${label}<span class="metric-icon ${tone}">${icon}</span></div><div class="metric-value">${value}</div><div class="metric-foot">${foot}</div></div>`;
}

function renderDashboard() {
  const todaySales = state.transactions.filter((transaction) => transaction.date === isoDate(new Date()));
  const todayTotal = todaySales.reduce((sum, transaction) => sum + transaction.total, 0);
  const lowProducts = state.products.filter(isLowStock);
  const expiringProducts = state.products.filter(isNearExpiry);
  const critical = lowProducts.length;
  const customerPoints = state.customers.reduce((sum, customer) => sum + customer.points, 0);
  const week = Array.from({ length: 7 }, (_, index) => {
    const date = new Date();
    date.setDate(date.getDate() - (6 - index));
    const key = isoDate(date);
    return { key, label: date.toLocaleDateString("en-IN", { weekday: "short" }), total: state.transactions.filter((transaction) => transaction.date === key).reduce((sum, transaction) => sum + transaction.total, 0) };
  });
  const maxDay = Math.max(...week.map((day) => day.total), 1);
  const bars = week.map((day) => `<div class="chart-column"><div class="chart-bar-wrap"><div class="chart-bar ${day.key === isoDate(new Date()) ? "is-today" : ""}" style="height:${Math.max(day.total ? 6 : 0, day.total / maxDay * 100)}%" data-value="${money(day.total)}"></div></div><span class="chart-label">${day.label}</span></div>`).join("");
  const recent = state.transactions.slice(0, 5);
  const attentionProducts = state.products.filter((product) => isLowStock(product) || isNearExpiry(product));
  const stockRows = attentionProducts.slice(0, 4).map((product) => {
    const earliest = product.batches.filter((batch) => batch.stock > 0).sort((a, b) => a.expiry.localeCompare(b.expiry))[0] || product.batches[0];
    const expiryText = isExpired(earliest) ? "Expired batch" : `${Math.max(0, escapeDateDays(earliest.expiry))} days to expiry`;
    return `<div class="stock-row"><div class="product-thumb ${product.tone}">${product.emoji}</div><div class="stock-info"><b>${escapeHTML(product.name)}</b><small>${escapeHTML(product.brand.split("·")[0].trim())} · ${expiryText}</small></div><div class="stock-level">${product.stock} left<small>${isLowStock(product) ? `Reorder at ${product.reorder}` : fmtDate(earliest.expiry)}</small></div></div>`;
  }).join("");
  content.innerHTML = `${pageHeading(`Good morning, ${escapeHTML(currentUser.name.split(" ")[0])} 👋`, "Here's what's happening at your pharmacy today.", `<button class="button" data-action="export-report">↓ &nbsp;Export</button><button class="button button-primary" data-page="sales"><span class="plus">+</span> New sale</button>`)}
    <section class="metrics-grid">
      ${metricCard("Today's sales", money(todayTotal), "↗", "green", "From recorded invoices today")}
      ${metricCard("Orders today", String(todaySales.length), "▤", "orange", "Invoices stored in SQLite")}
      ${metricCard("Units on hand", state.products.reduce((sum, product) => sum + product.stock, 0).toLocaleString("en-IN"), "▣", "coral", `<span class="negative">${critical} low stock</span> · ${expiringProducts.length} need expiry review`)}
      ${metricCard("Active loyalty points", customerPoints.toLocaleString("en-IN"), "✧", "lilac", `Across ${state.customers.length} registered customers`)}
    </section>
    <section class="dashboard-grid">
      <div class="panel"><div class="panel-header"><div><h2>Sales overview</h2><div class="panel-sub">Your store's performance this week</div></div><select class="select-small" aria-label="Sales overview range"><option>This week</option><option>This month</option></select></div>
        <div class="sales-chart"><div class="chart-y-axis"><span>${money(maxDay)}</span><span>${money(maxDay*.75)}</span><span>${money(maxDay*.5)}</span><span>${money(maxDay*.25)}</span><span>${money(0)}</span></div><div class="chart-columns">${bars}</div></div>
      </div>
      <div class="panel"><div class="panel-header"><div><h2>Stock alerts</h2><div class="panel-sub">Low stock and expiry attention</div></div><span class="status-pill status-low">${attentionProducts.length} alerts</span></div>
        <div class="stock-list">${stockRows || `<div class="empty-state"><span>✓</span>All products are well stocked.</div>`}</div><div class="panel-footer"><button class="inline-link" data-page="inventory">View inventory →</button></div>
      </div>
    </section>
    <section class="bottom-grid">
      <div class="panel"><div class="panel-header"><div><h2>Recent transactions</h2><div class="panel-sub">The latest activity at your store</div></div><button class="inline-link" data-page="reports">View all →</button></div>
        <div class="table-wrap"><table><thead><tr><th>INVOICE</th><th>CUSTOMER</th><th>ITEMS</th><th>AMOUNT</th><th>PAYMENT</th><th>SOLD BY</th></tr></thead><tbody>${recent.map((transaction) => `<tr><td class="strong-cell">${escapeHTML(transaction.id)}<div class="sub-cell">${fmtDate(transaction.date)}</div></td><td>${escapeHTML(transaction.customerName)}</td><td>${transaction.items} items</td><td class="strong-cell">${money(transaction.total)}</td><td><span class="status-pill ${transaction.status === "Credit" ? "status-credit" : "status-paid"}">${escapeHTML(transaction.payment)}</span></td><td>${soldByLabel(transaction)}</td></tr>`).join("")}</tbody></table></div>
      </div>
      <div class="panel"><div class="panel-header"><div><h2>Loyalty at a glance</h2><div class="panel-sub">Your customers keep coming back</div></div><button class="inline-link" data-page="rewards">Manage →</button></div>
        <div class="loyalty-card"><div class="loyalty-title">The Phoebix Rewards Club</div><p>Reward every visit. Members earn ${state.rules.pointsPerRupee} point for every ${money(state.rules.earnPer)} spent.</p><div class="loyalty-points"><span>Points in circulation</span><b>${customerPoints.toLocaleString("en-IN")}</b></div></div>
        <div class="tier-row"><div class="tier"><b>Member</b><span>Under ₹5,000</span><div class="bar-track"><span style="width:28%"></span></div></div><div class="tier"><b>Silver</b><span>₹5k – ₹10k</span><div class="bar-track"><span style="width:56%"></span></div></div><div class="tier"><b>Gold</b><span>₹10,000+</span><div class="bar-track"><span style="width:82%"></span></div></div></div>
      </div>
    </section>`;
}

function renderInventory() {
  const search = (document.getElementById("inventory-search")?.value || "").toLowerCase();
  const batchRows = state.products.flatMap((product) => product.batches.map((batch) => ({ product, batch })));
  const filtered = batchRows.filter(({ product, batch }) => {
    const matchesText = `${product.name} ${product.brand} ${batch.batch} ${product.hsn}`.toLowerCase().includes(search);
    const matchesFilter = inventoryFilter === "All products" || (inventoryFilter === "Low stock" && isLowStock(product)) || (inventoryFilter === "Near expiry" && escapeDateDays(batch.expiry) <= 90);
    return matchesText && matchesFilter;
  });
  const action = `<button class="button" data-action="export-inventory">↓ &nbsp;Export</button><button class="button button-primary" data-action="add-stock"><span class="plus">+</span> Add product</button>`;
  content.innerHTML = `${pageHeading("Inventory", "Keep an eye on batches, expiry dates and what's running low.", action)}
    <section class="metrics-grid">
      ${metricCard("Total products", state.products.length, "▣", "green", "Across all categories")}
      ${metricCard("Units on hand", state.products.reduce((sum, product) => sum + product.stock, 0).toLocaleString("en-IN"), "▤", "orange", "Available to sell")}
      ${metricCard("Low stock", state.products.filter(isLowStock).length, "!", "coral", "At or below reorder level")}
      ${metricCard("Expiry attention", state.products.filter(isNearExpiry).length, "◷", "lilac", "Expired or due within 90 days")}
    </section>
    <section class="panel table-panel"><div class="filter-row"><input id="inventory-search" class="filter-input" placeholder="⌕  Search product, batch or HSN..." value="${escapeHTML(document.getElementById("inventory-search")?.value || "")}"><select class="filter-select" id="inventory-filter"><option ${inventoryFilter === "All products" ? "selected" : ""}>All products</option><option ${inventoryFilter === "Low stock" ? "selected" : ""}>Low stock</option><option ${inventoryFilter === "Near expiry" ? "selected" : ""}>Near expiry</option></select><button class="button" data-action="add-stock">＋ Stock intake</button></div>
    <div class="table-wrap"><table class="data-table"><thead><tr><th>PRODUCT</th><th>BATCH / HSN</th><th>EXPIRY</th><th>BATCH STOCK</th><th>REORDER AT</th><th>SELLING PRICE</th><th>GST</th><th></th></tr></thead><tbody>${filtered.map(({ product, batch }) => {
      const expiryDays = escapeDateDays(batch.expiry);
      const expiryStatus = expiryDays < 0 ? `<span class="status-pill status-low">Expired</span>` : expiryDays <= 90 ? `<span class="status-pill status-expiry">Due soon</span>` : "";
      const stockStatus = isLowStock(product) ? "status-low" : "status-ok";
      return `<tr><td><div class="product-name-cell"><div class="product-thumb ${product.tone}">${product.emoji}</div><div><b>${escapeHTML(product.name)}</b><small>${escapeHTML(product.brand)} · ${product.stock} total units</small></div></div></td><td>${escapeHTML(batch.batch)}<div class="sub-cell">HSN ${escapeHTML(product.hsn)}</div></td><td>${fmtDate(batch.expiry)}<div class="sub-cell">${expiryStatus || `${expiryDays} days`}</div></td><td><span class="status-pill ${stockStatus}">${batch.stock} units</span></td><td>${product.reorder} units</td><td class="strong-cell">${money(product.price)}<div class="sub-cell">MRP ${money(product.mrp)}</div></td><td>${product.gst}%</td><td><button class="table-actions" data-action="receive-stock" data-id="${product.id}" data-batch="${escapeHTML(batch.id)}" aria-label="Receive stock for ${escapeHTML(batch.batch)}">＋</button></td></tr>`;
    }).join("") || `<tr><td colspan="8"><div class="empty-state"><span>⌕</span>No matching batches found.</div></td></tr>`}</tbody></table></div>
    <div class="pagination"><span>Showing ${filtered.length} of ${batchRows.length} batches</span><div class="pagination-controls"><button class="page-btn selected">1</button></div></div></section>`;
}

function renderCustomers() {
  const search = (document.getElementById("customer-search")?.value || customerFilter).toLowerCase();
  const customers = state.customers.filter((customer) => `${customer.name} ${customer.phone} ${customer.email}`.toLowerCase().includes(search) && (customerTierFilter === "All members" || customer.tier === customerTierFilter));
  const points = state.customers.reduce((sum, customer) => sum + customer.points, 0);
  content.innerHTML = `${pageHeading("Customers", "Get to know your regulars and make every visit count.", `<button class="button" data-action="export-customers">↓ &nbsp;Export</button><button class="button button-primary" data-action="add-customer"><span class="plus">+</span> Add customer</button>`)}
    <section class="metrics-grid">
      ${metricCard("Total customers", state.customers.length, "♙", "green", "Registered loyalty members")}
      ${metricCard("Points outstanding", points.toLocaleString("en-IN"), "✧", "lilac", "Redeemable rewards balance")}
      ${metricCard("Gold members", state.customers.filter((customer) => customer.tier === "Gold").length, "★", "orange", "Spent over ₹10,000")}
      ${metricCard("New this month", state.customers.filter((customer) => customer.joined.slice(0, 7) === isoDate(new Date()).slice(0, 7)).length, "↗", "coral", "Joined this calendar month")}
    </section>
    <section class="panel table-panel"><div class="filter-row"><input id="customer-search" class="filter-input" placeholder="⌕  Search name, phone or email..." value="${escapeHTML(search)}"><select class="filter-select" id="customer-tier-filter"><option ${customerTierFilter==="All members"?"selected":""}>All members</option><option ${customerTierFilter==="Gold"?"selected":""}>Gold</option><option ${customerTierFilter==="Silver"?"selected":""}>Silver</option><option ${customerTierFilter==="Member"?"selected":""}>Member</option></select><button class="button" data-action="export-customers">Export list</button></div>
    <div class="table-wrap"><table class="data-table"><thead><tr><th>CUSTOMER</th><th>PHONE</th><th>MEMBER SINCE</th><th>VISITS</th><th>LIFETIME SPEND</th><th>POINTS BALANCE</th><th>TIER</th><th></th></tr></thead><tbody>${customers.map((customer) => `<tr><td><div class="customer-cell"><div class="avatar">${escapeHTML(customer.initials || initialsFor(customer.name))}</div><div><b>${escapeHTML(customer.name)}</b><small>${escapeHTML(customer.email)}</small></div></div></td><td>${escapeHTML(customer.phone)}</td><td>${fmtDate(customer.joined)}</td><td>${customer.visits}</td><td class="strong-cell">${money(customer.spent)}</td><td class="points-cell">${customer.points} pts</td><td><span class="status-pill ${customer.tier === "Gold" ? "status-credit" : "status-ok"}">${escapeHTML(customer.tier)}</span></td><td><button class="table-actions" data-action="adjust-points" data-id="${customer.id}" aria-label="Adjust ${escapeHTML(customer.name)} points">···</button></td></tr>`).join("") || `<tr><td colspan="8"><div class="empty-state"><span>♙</span>No customers match your search.</div></td></tr>`}</tbody></table></div><div class="pagination"><span>Showing ${customers.length} of ${state.customers.length} customers</span><div class="pagination-controls"><button class="page-btn selected">1</button></div></div></section>`;
}

function renderRewards() {
  const points = state.customers.reduce((sum, customer) => sum + customer.points, 0);
  const month = isoDate(new Date()).slice(0, 7);
  const monthTransactions = state.transactions.filter((transaction) => transaction.date.slice(0, 7) === month);
  const pointsEarned = monthTransactions.reduce((sum, transaction) => sum + (transaction.earned || 0), 0);
  const redeemedValue = state.transactions.reduce((sum, transaction) => sum + (transaction.redeemed || 0), 0);
  const memberVisits = state.transactions.length ? Math.round(state.transactions.filter((transaction) => transaction.customerId).length / state.transactions.length * 100) : 0;
  const recentRedemptions = state.transactions.filter((transaction) => transaction.redeemed > 0).slice(0, 3);
  const offersList = state.offers.length ? state.offers.map((offer) => `<div class="rule-row"><span class="rule-icon">%</span><div class="rule-copy"><b>${escapeHTML(offer.name)}</b><small>${offer.type === "percent" ? `${offer.discount}% off` : `${money(offer.discount)} off`} · Valid until ${fmtDate(offer.end)}</small></div><button class="switch ${offer.enabled ? "on" : ""}" data-action="toggle-offer" data-id="${offer.id}" aria-label="Toggle ${escapeHTML(offer.name)}"></button></div>`).join("") : `<div class="empty-state"><span>％</span>No custom offers yet. Create one for your customers.</div>`;
  content.innerHTML = `${pageHeading("Rewards & offers", "Make loyalty feel a little more rewarding.", `<button class="button" data-action="edit-rules">⚙ &nbsp;Program settings</button><button class="button button-primary" data-action="new-offer"><span class="plus">+</span> Create offer</button>`)}
    <div class="program-banner"><div><h2>✧ &nbsp; The Phoebix Rewards Club</h2><p>Give your customers a reason to choose you, every time.</p></div><div class="program-score">${points.toLocaleString("en-IN")}<small>points in circulation</small></div></div>
    <div class="metrics-grid">
      ${metricCard("Active members", state.customers.length, "♙", "green", "Across 3 membership tiers")}
      ${metricCard("Points earned this month", pointsEarned.toLocaleString("en-IN"), "✧", "lilac", "From recorded loyalty sales")}
      ${metricCard("Rewards redeemed", money(redeemedValue), "↗", "orange", "Value from recorded redemptions")}
      ${metricCard("Member visits", `${memberVisits}%`, "▤", "coral", "Share of recorded bills")}
    </div>
    <div class="rewards-grid">
      <section class="reward-card"><h2>Earning & redemption</h2><p>Set simple rules customers can remember.</p>
        <div class="reward-earn"><div><b>Points per purchase</b><small>Earn ${state.rules.pointsPerRupee} point for every ${money(state.rules.earnPer)} spent</small></div><strong>On</strong></div>
        <div class="reward-earn"><div><b>Points value</b><small>Each point is worth</small></div><strong>${money(1)}</strong></div>
        <div class="reward-earn"><div><b>Redemption limit</b><small>Maximum share of eligible bill</small></div><strong>${state.rules.redeemMaxPercent}%</strong></div>
        <div class="reward-earn"><div><b>Member tiers</b><small>Member → Silver → Gold by lifetime spend</small></div><button class="inline-link" data-action="edit-rules">Edit tiers</button></div>
      </section>
      <section class="reward-card"><h2>Offers & perks</h2><p>Choose the moments you want to celebrate.</p>
        <div class="rule-row"><span class="rule-icon">🎂</span><div class="rule-copy"><b>Birthday treat</b><small>10% off during their birthday month</small></div><button class="switch ${state.rules.birthday ? "on" : ""}" data-action="toggle-rule" data-rule="birthday" aria-label="Toggle birthday treat"></button></div>
        <div class="rule-row"><span class="rule-icon">🌿</span><div class="rule-copy"><b>Wellness Wednesday</b><small>Extra points on wellness products</small></div><button class="switch ${state.rules.wellness ? "on" : ""}" data-action="toggle-rule" data-rule="wellness" aria-label="Toggle wellness Wednesday"></button></div>
        <div class="rule-row"><span class="rule-icon">↻</span><div class="rule-copy"><b>Monthly refill reminder</b><small>Bring customers back for their refills</small></div><button class="switch ${state.rules.refill ? "on" : ""}" data-action="toggle-rule" data-rule="refill" aria-label="Toggle refill reminder"></button></div>
        ${offersList}
        <div class="panel-footer"><button class="inline-link" data-action="new-offer">＋ Create a custom offer</button></div>
      </section>
      <section class="reward-card"><h2>Your membership tiers</h2><p>Progress feels good. Show members what's next.</p>
        <div class="tier-row"><div class="tier"><b>Member</b><span>₹0 – ₹4,999</span><div class="bar-track"><span style="width:28%"></span></div></div><div class="tier"><b>Silver</b><span>₹5,000 – ₹9,999</span><div class="bar-track"><span style="width:56%"></span></div></div><div class="tier"><b>Gold</b><span>₹10,000+</span><div class="bar-track"><span style="width:82%"></span></div></div></div>
      </section>
      <section class="reward-card"><h2>Recent redemptions</h2><p>Keep track of rewards your members love.</p>
        ${recentRedemptions.length ? recentRedemptions.map((transaction) => `<div class="rule-row"><div class="avatar">${escapeHTML(initialsFor(transaction.customerName))}</div><div class="rule-copy"><b>${escapeHTML(transaction.customerName)}</b><small>${escapeHTML(transaction.id)} · ${fmtDate(transaction.date)}</small></div><strong>${transaction.redeemed} pts</strong></div>`).join("") : `<div class="empty-state"><span>✧</span>No recorded point redemptions yet.</div>`}
      </section>
    </div>`;
}

function renderReports() {
  const total = state.transactions.reduce((sum, transaction) => sum + transaction.total, 0);
  const week = Array.from({ length: 7 }, (_, index) => {
    const date = new Date();
    date.setDate(date.getDate() - (6 - index));
    const key = isoDate(date);
    return { key, label: date.toLocaleDateString("en-IN", { weekday: "short" }), total: state.transactions.filter((transaction) => transaction.date === key).reduce((sum, transaction) => sum + transaction.total, 0) };
  });
  const maxDay = Math.max(...week.map((day) => day.total), 1);
  const categoryTotals = [...new Set(state.products.map((product) => product.category))].map((category) => ({
    category,
    total: state.products.filter((product) => product.category === category).reduce((sum, product) => sum + product.stock * product.price, 0)
  })).sort((a, b) => b.total - a.total);
  const max = Math.max(...categoryTotals.map((row) => row.total), 1);
  content.innerHTML = `${pageHeading("Reports", "A clearer picture of how your pharmacy is doing.", `<select class="filter-select" aria-label="Report period"><option>This month</option><option>This week</option><option>This year</option></select><button class="button" data-action="export-report">↓ &nbsp;Export report</button>`)}
    <section class="metrics-grid">${metricCard("Total sales", money(total), "↗", "green", "From recorded transactions")}${metricCard("Transactions", state.transactions.length, "▤", "orange", "Bills created in this workspace")}${metricCard("Average basket", money(total / Math.max(state.transactions.length, 1)), "▣", "coral", "Average bill value")}${metricCard("Loyalty customers", state.customers.length, "✧", "lilac", "Registered members")}</section>
    <div class="report-grid">
      <section class="report-card"><h2>Sales by day</h2><p>Revenue trend for the current week</p><div class="report-highlight">${money(total)} <small>recorded sales</small></div>
        <div class="sales-chart"><div class="chart-y-axis"><span>${money(maxDay)}</span><span>${money(maxDay*.75)}</span><span>${money(maxDay*.5)}</span><span>${money(maxDay*.25)}</span><span>${money(0)}</span></div><div class="chart-columns">${week.map((day)=>`<div class="chart-column"><div class="chart-bar-wrap"><div class="chart-bar ${day.key===isoDate(new Date())?"is-today":""}" style="height:${Math.max(day.total?6:0,day.total/maxDay*100)}%" data-value="${money(day.total)}"></div></div><span class="chart-label">${day.label}</span></div>`).join("")}</div></div>
      </section>
      <section class="report-card"><h2>Inventory value by category</h2><p>Current on-hand stock at selling price</p>${categoryTotals.map((row)=>`<div class="category-bar-row"><span>${escapeHTML(row.category)}</span><div class="bar-track"><span style="width:${Math.max(3, row.total/max*100)}%"></span></div><strong>${money(row.total)}</strong></div>`).join("")}</section>
      <section class="report-card"><h2>Payment mix</h2><p>Recorded invoice payment methods</p>${["UPI","Cash","Card","Credit"].map((method)=>{const count=state.transactions.filter((transaction)=>transaction.payment===method).length;return `<div class="category-bar-row"><span>${method}</span><div class="bar-track"><span style="width:${Math.max(count?5:0,count/Math.max(state.transactions.length,1)*100)}%"></span></div><strong>${count}</strong></div>`}).join("")}</section>
      <section class="report-card"><h2>Recent invoices</h2><p>Print a customer copy when needed</p><div class="table-wrap"><table><thead><tr><th>INVOICE</th><th>CUSTOMER</th><th>AMOUNT</th><th>SOLD BY</th><th></th></tr></thead><tbody>${state.transactions.slice(0,5).map((transaction)=>`<tr><td class="strong-cell">${escapeHTML(transaction.id)}<div class="sub-cell">${fmtDate(transaction.date)}</div></td><td>${escapeHTML(transaction.customerName)}</td><td class="strong-cell">${money(transaction.total)}</td><td>${soldByLabel(transaction)}</td><td><button class="inline-link" data-action="print-invoice" data-id="${escapeHTML(transaction.id)}">Print</button></td></tr>`).join("")}</tbody></table></div></section>
    </div>`;
}

function cartTotals() {
  const subtotal = cart.reduce((sum, line) => sum + line.qty * line.price, 0);
  const offer = state.offers.find((entry) => entry.id === selectedOfferId && entry.enabled && entry.end >= isoDate(new Date()));
  const discount = Math.min(offer
    ? (offer.type === "percent" ? subtotal * offer.discount / 100 : offer.discount)
    : (discountType === "percent" ? subtotal * Number(discountInput || 0) / 100 : Number(discountInput || 0)), subtotal);
  const taxable = Math.max(0, subtotal - discount);
  const tax = cart.reduce((sum, line) => sum + line.qty * line.price * (subtotal ? taxable / subtotal : 0) * line.gst / 100, 0);
  const customer = customerById(selectedCustomer);
  const gross = taxable + tax;
  const maxRedeem = customer ? Math.min(customer.points, Math.floor(gross * state.rules.redeemMaxPercent / 100)) : 0;
  const redeem = Math.min(maxRedeem, Number(redeemInput || 0));
  return { subtotal, taxable, tax, discount, redeem, total: Math.max(0, gross - redeem) };
}

function renderSales() {
  const filtered = state.products.filter((product) => (posCategory === "All items" || product.category === posCategory) && `${product.name} ${product.brand}`.toLowerCase().includes(posSearch.toLowerCase()));
  const categories = ["All items", ...new Set(state.products.map((product) => product.category))];
  const totals = cartTotals();
  const member = customerById(selectedCustomer);
  const maxRedeem = member ? Math.min(member.points, Math.floor((totals.taxable + totals.tax) * state.rules.redeemMaxPercent / 100)) : 0;
  const customerOptions = state.customers.map((customer) => `<option value="${customer.id}" ${selectedCustomer === customer.id ? "selected" : ""}>${escapeHTML(customer.name)} · ${customer.points} pts</option>`).join("");
  content.innerHTML = `${pageHeading("Point of sale", "A quick, clear checkout for every customer.", `<span class="install-note">● &nbsp;Billing ready</span>`)}
    <div class="sales-layout"><section>
      <div class="sales-toolbar"><input class="filter-input" id="pos-search" placeholder="⌕  Search medicines, wellness and more..." value="${escapeHTML(posSearch)}"><button class="button" data-action="add-stock">＋ Product</button></div>
      <div class="category-tabs">${categories.map((category)=>`<button class="category-tab ${posCategory===category?"selected":""}" data-action="pos-category" data-category="${escapeHTML(category)}">${escapeHTML(category)}</button>`).join("")}</div>
      <div class="pos-grid">${filtered.map((product)=>{
        const sellable = product.batches.filter((batch)=>!isExpired(batch)).reduce((sum,batch)=>sum+batch.stock,0);
        const availability = sellable ? `${sellable} available` : product.stock ? "Expired batch" : "Out of stock";
        return `<button class="pos-product" data-action="add-to-cart" data-id="${product.id}" ${hasSellableStock(product)?"":"disabled"}><div class="product-thumb ${product.tone}">${product.emoji}</div><h3>${escapeHTML(product.name)}</h3><p>${escapeHTML(product.brand)} · GST ${product.gst}%</p><div class="pos-product-bottom"><b>${money(product.price)}</b><span>${availability}</span></div></button>`;
      }).join("") || `<div class="no-results">No products match your search.</div>`}</div>
    </section>
    <section class="panel cart-panel"><div class="cart-head"><h2>Current bill</h2><span class="cart-count">${cart.reduce((sum,line)=>sum+line.qty,0)} items</span></div>
      <div class="customer-picker"><select class="customer-select" id="sale-customer"><option value="">Walk-in customer</option>${customerOptions}</select><button type="button" class="button" data-action="add-sale-customer" title="Add a new customer">+ New</button></div>
      <div class="cart-items">${cart.length?cart.map((line)=>`<div class="cart-line"><div><div class="cart-line-name">${escapeHTML(line.name)}</div><div class="cart-line-meta">Batch ${escapeHTML(line.batch)} · Exp ${fmtDate(line.expiry)} · ${line.gst}% GST</div><div class="qty-control"><button data-action="qty-minus" data-id="${line.id}" data-batch="${line.batchId}" aria-label="Decrease quantity">−</button><span>${line.qty}</span><button data-action="qty-plus" data-id="${line.id}" data-batch="${line.batchId}" aria-label="Increase quantity">+</button></div></div><div class="cart-line-price">${money(line.qty*line.price)}<div class="cart-line-meta">${money(line.price)} / unit</div></div></div>`).join(""):`<div class="cart-empty"><span>▤</span>Your bill is looking a little empty.<br>Add a product to get started.</div>`}</div>
      <div class="cart-summary">      <div class="summary-row"><span>Subtotal</span><b data-subtotal>${money(totals.subtotal)}</b></div><div class="summary-row"><span>GST after discount</span><b data-tax>${money(totals.tax)}</b></div>
      <div class="summary-row"><span>${selectedOfferId ? "Offer discount" : "Bill discount"}</span><span class="discount-controls"><small data-discount>${money(totals.discount)}</small><input id="discount-input" type="number" min="0" value="${escapeHTML(discountInput)}" aria-label="Discount amount" ${selectedOfferId?"disabled":""}><select id="discount-type" aria-label="Discount type" ${selectedOfferId?"disabled":""}><option value="percent" ${discountType==="percent"?"selected":""}>%</option><option value="fixed" ${discountType==="fixed"?"selected":""}>₹</option></select></span></div>
        ${state.offers.some((offer)=>offer.enabled && offer.end >= isoDate(new Date())) ? `<div class="summary-row"><span>Apply offer</span><select id="sale-offer" class="filter-select"><option value="">No offer</option>${state.offers.filter((offer)=>offer.enabled && offer.end >= isoDate(new Date())).map((offer)=>`<option value="${offer.id}" ${selectedOfferId===offer.id?"selected":""}>${escapeHTML(offer.name)} · ${offer.type==="percent"?`${offer.discount}%`:`${money(offer.discount)}`} off</option>`).join("")}</select></div>` : ""}
        ${member?`<div class="redeem-line"><span>Redeem points <small data-redeem-limit>(max ${maxRedeem} pts)</small></span><input id="redeem-input" type="number" min="0" max="${maxRedeem}" value="${escapeHTML(redeemInput)}" aria-label="Points to redeem"></div>`:""}
        <div class="summary-row"><span>Payment method</span><select id="payment-method" class="filter-select"><option value="UPI" ${paymentMethod==="UPI"?"selected":""} ${phonepeConfigured?"":"disabled"}>UPI · PhonePe</option><option value="Cash" ${paymentMethod==="Cash"?"selected":""}>Cash</option><option value="Card" ${paymentMethod==="Card"?"selected":""} ${phonepeConfigured?"":"disabled"}>Card · PhonePe</option><option value="Credit" ${paymentMethod==="Credit"?"selected":""}>Credit</option></select></div>
        ${phonepeConfigured ? "" : `<p class="cart-note">PhonePe UPI and card payments need sandbox credentials in .env.</p>`}
        <div class="summary-row summary-total"><span>Total payable</span><b data-total>${money(totals.total)}</b></div>
        <button class="button button-primary checkout-button" data-action="checkout" ${cart.length?"":"disabled"}>Charge ${money(totals.total)} &nbsp; →</button><p class="cart-note">${paymentMethod==="UPI"||paymentMethod==="Card"?"PhonePe verifies payment before saving the invoice.":"GST invoice · Payment recorded at checkout"}</p>
      </div>
    </section></div>`;
}

function render() {
  document.getElementById("inventory-badge").textContent = state.products.filter(isLowStock).length || "";
  document.querySelectorAll("[data-store-name]").forEach((element) => { element.textContent = state.store.name; });
  document.querySelectorAll("[data-store-city]").forEach((element) => { element.textContent = state.store.city; });
  document.querySelectorAll("[data-store-branch]").forEach((element) => { element.textContent = state.store.branch; });
  if (activePage === "dashboard") renderDashboard();
  else if (activePage === "sales") renderSales();
  else if (activePage === "inventory") renderInventory();
  else if (activePage === "customers") renderCustomers();
  else if (activePage === "rewards") renderRewards();
  else if (activePage === "users") renderUsers();
  else renderReports();
}

function refreshCartSummary() {
  const totals = cartTotals();
  const member = customerById(selectedCustomer);
  const maxRedeem = member ? Math.min(member.points, Math.floor((totals.taxable + totals.tax) * state.rules.redeemMaxPercent / 100)) : 0;
  const summary = content.querySelector(".cart-summary");
  if (!summary) return;
  summary.querySelector("[data-subtotal]").textContent = money(totals.subtotal);
  summary.querySelector("[data-tax]").textContent = money(totals.tax);
  summary.querySelector("[data-discount]").textContent = money(totals.discount);
  summary.querySelector("[data-total]").textContent = money(totals.total);
  summary.querySelector(".checkout-button").textContent = `Charge ${money(totals.total)} →`;
  const redeemInputElement = summary.querySelector("#redeem-input");
  if (redeemInputElement) {
    redeemInputElement.max = String(maxRedeem);
    summary.querySelector("[data-redeem-limit]").textContent = `(max ${maxRedeem} pts)`;
  }
}

function openModal(title, subtitle, body, submitLabel, onSubmit) {
  modalRoot.innerHTML = `<div class="modal-backdrop" data-action="close-modal"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title"><div class="modal-head"><div><h2 id="modal-title">${title}</h2><p>${subtitle}</p></div><button class="modal-close" data-action="close-modal" aria-label="Close dialog">×</button></div><form id="modal-form">${body}<div class="modal-actions"><button type="button" class="button" data-action="close-modal">Cancel</button><button type="button" id="modal-submit" class="button button-primary">${submitLabel}</button></div></form></section></div>`;
  const form = modalRoot.querySelector("#modal-form");
  const submitForm = () => {
    if (!form.reportValidity()) return;
    onSubmit(Object.fromEntries(new FormData(form).entries()));
  };
  modalRoot.querySelector("#modal-submit").addEventListener("click", submitForm);
  form.addEventListener("submit", (event) => event.preventDefault());
  form.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.target.tagName !== "BUTTON") {
      event.preventDefault();
      submitForm();
    }
  });
}

function showAddProduct() {
  openModal("Add a product", "Add a medicine or pharmacy item to your catalog.", `<div class="form-grid">
    <div class="form-field full"><label for="p-name">Product name</label><input id="p-name" name="name" required placeholder="e.g. Vitamin C 500 mg"></div>
    <div class="form-field"><label for="p-brand">Brand & pack size</label><input id="p-brand" name="brand" required placeholder="Brand · 10 tablets"></div>
    <div class="form-field"><label for="p-category">Category</label><select id="p-category" name="category"><option>Tablets</option><option>Syrups</option><option>Wellness</option><option>Devices</option><option>Personal care</option><option>Other</option></select></div>
    <div class="form-field"><label for="p-batch">Batch number</label><input id="p-batch" name="batch" required></div>
    <div class="form-field"><label for="p-hsn">HSN code</label><input id="p-hsn" name="hsn" required value="30049099"></div>
    <div class="form-field"><label for="p-expiry">Expiry date</label><input id="p-expiry" name="expiry" type="date" required min="${isoDate(new Date())}"></div>
    <div class="form-field"><label for="p-stock">Opening stock</label><input id="p-stock" name="stock" type="number" min="0" value="0" required></div>
    <div class="form-field"><label for="p-reorder">Reorder at</label><input id="p-reorder" name="reorder" type="number" min="0" value="10" required></div>
    <div class="form-field"><label for="p-price">Selling price (₹)</label><input id="p-price" name="price" type="number" step=".01" min="0" required></div>
    <div class="form-field"><label for="p-mrp">MRP (₹)</label><input id="p-mrp" name="mrp" type="number" step=".01" min="0" required></div>
    <div class="form-field"><label for="p-gst">GST slab</label><select id="p-gst" name="gst"><option>0</option><option>5</option><option>12</option><option>18</option><option>28</option></select></div>
  </div>`, "Save product", (data) => {
    if (Number(data.price) > Number(data.mrp)) return toast("Selling price cannot be higher than MRP.");
    const id = `p${Date.now()}`;
    state.products.unshift({ id, ...data, stock: Number(data.stock), batches: [{ id: `${id}-batch-1`, batch: data.batch.trim(), expiry: data.expiry, stock: Number(data.stock) }], reorder: Number(data.reorder), price: Number(data.price), mrp: Number(data.mrp), gst: Number(data.gst), emoji: "💊", tone: "thumb-blue" });
    persist(); modalRoot.innerHTML = ""; render(); toast("Product added to inventory.");
  });
}

function showReceiveStock(productId, batchId) {
  const product = productById(productId);
  const currentBatch = batchById(product, batchId);
  if (!product || !currentBatch) return;
  openModal("Receive stock", `${product.name} · receive this batch again or enter a new batch number.`, `<div class="form-grid">
    <div class="form-field full"><label>Product</label><input value="${escapeHTML(product.name)}" disabled></div>
    <div class="form-field"><label for="receive-qty">Quantity received</label><input id="receive-qty" name="qty" type="number" min="1" value="1" required></div>
    <div class="form-field"><label for="receive-batch">Batch number</label><input id="receive-batch" name="batch" value="${escapeHTML(currentBatch.batch)}" required></div>
    <div class="form-field full"><label for="receive-expiry">Batch expiry date</label><input id="receive-expiry" name="expiry" type="date" value="${currentBatch.expiry}" min="${isoDate(new Date())}" required></div>
  </div>`, "Update stock", (data) => {
    const qty = Number(data.qty);
    if (!Number.isInteger(qty) || qty < 1) return toast("Enter a whole quantity greater than zero.");
    if (data.expiry < isoDate(new Date())) return toast("Expired batches cannot be received into saleable stock.");
    const batchNumber = data.batch.trim();
    const matchingBatch = product.batches.find((batch) => batch.batch.toUpperCase() === batchNumber.toUpperCase());
    if (matchingBatch && matchingBatch.expiry !== data.expiry && matchingBatch.stock > 0) return toast("A batch number cannot have two expiry dates. Enter a distinct batch number.");
    if (matchingBatch) {
      matchingBatch.expiry = data.expiry;
      matchingBatch.stock += qty;
    } else {
      product.batches.push({ id: `${product.id}-batch-${Date.now()}`, batch: batchNumber, expiry: data.expiry, stock: qty });
    }
    product.batches.sort((a, b) => a.expiry.localeCompare(b.expiry));
    syncProductStock(product);
    persist(); modalRoot.innerHTML = ""; render(); toast(`${qty} units received in batch ${batchNumber}.`);
  });
}

function showAddCustomer(onAdded) {
  openModal("Add a customer", "Create a member profile for your pharmacy.", `<div class="form-grid">
    <div class="form-field full"><label for="c-name">Full name</label><input id="c-name" name="name" required></div>
    <div class="form-field"><label for="c-phone">Mobile number</label><input id="c-phone" name="phone" type="tel" required placeholder="+91 98765 43210"></div>
    <div class="form-field"><label for="c-email">Email (optional)</label><input id="c-email" name="email" type="email" placeholder="name@example.com"></div>
    <div class="form-field full"><label for="c-address">Billing address (optional)</label><input id="c-address" name="address" autocomplete="street-address"></div>
    <div class="form-field"><label for="c-state">Billing state / UT (optional)</label><input id="c-state" name="state" autocomplete="address-level1"></div>
    <div class="form-field"><label for="c-gstin">Customer GSTIN (optional)</label><input id="c-gstin" name="gstin" maxlength="15" autocapitalize="characters"></div>
    <div class="form-field"><label for="c-license">Drug licence (optional)</label><input id="c-license" name="drugLicense"></div>
  </div>`, "Add customer", async (data) => {
    if (!databaseReady) return toast("The database is not connected. Start Phoebix and reload.");
    const submit = modalRoot.querySelector("#modal-submit");
    submit.disabled = true;
    try {
      const response = await fetch("/api/customers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...data, expectedRevision: databaseRevision }),
        cache: "no-store"
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.error || `Database save failed (${response.status}). Make sure Phoebix is running.`);
      databaseRevision = result.revision;
      state.customers.unshift(result.customer);
      modalRoot.innerHTML = "";
      onAdded?.(result.customer);
      render();
      toast("Customer saved to the database.");
    } catch (error) {
      submit.disabled = false;
      toast(error instanceof TypeError ? "Cannot reach the Phoebix server. Make sure it is running." : error.message);
    }
  });
}

function showStoreSettings() {
  const store = state.store;
  const bank = store.bank;
  const isAdmin = currentUser?.role === "admin";
  const lock = isAdmin ? "" : "readonly";
  openModal("Pharmacy & tax profile", "Set the business details printed on your invoices.", `<div class="form-grid">
    <div class="form-field full"><label for="store-name">Pharmacy name</label><input id="store-name" name="name" value="${escapeHTML(store.name)}" required></div>
    <div class="form-field full"><label for="store-address">Address</label><input id="store-address" name="address" value="${escapeHTML(store.address)}" autocomplete="street-address"></div>
    <div class="form-field"><label for="store-city">City</label><input id="store-city" name="city" value="${escapeHTML(store.city)}" required></div>
    <div class="form-field"><label for="store-state">State / UT</label><input id="store-state" name="state" value="${escapeHTML(store.state)}" required></div>
    <div class="form-field"><label for="store-pincode">PIN code</label><input id="store-pincode" name="pincode" inputmode="numeric" value="${escapeHTML(store.pincode)}"></div>
    <div class="form-field"><label for="store-phone">Business phone</label><input id="store-phone" name="phone" type="tel" value="${escapeHTML(store.phone)}"></div>
    <div class="form-field"><label for="store-gstin">GSTIN</label><input id="store-gstin" name="gstin" maxlength="15" autocapitalize="characters" value="${escapeHTML(store.gstin)}" placeholder="15-character GSTIN"></div>
    <div class="form-field"><label for="store-license">Drug licence number</label><input id="store-license" name="drugLicense" value="${escapeHTML(store.drugLicense)}"></div>
    <div class="form-field"><label for="store-branch">Branch label</label><input id="store-branch" name="branch" value="${escapeHTML(store.branch)}"></div>
    <div class="form-field"><label for="store-prefix">Invoice prefix</label><input id="store-prefix" name="invoicePrefix" maxlength="8" value="${escapeHTML(store.invoicePrefix)}" required></div>
    <div class="form-section full"><h3>Bank account for payments</h3><p>${isAdmin ? "Customers pay into this account. It is printed on every invoice." : "Only an administrator can change the bank details."}</p></div>
    <div class="form-field full"><label for="bank-holder">Account holder name</label><input id="bank-holder" name="bankAccountHolder" value="${escapeHTML(bank.accountHolder)}" ${lock}></div>
    <div class="form-field"><label for="bank-name">Bank name</label><input id="bank-name" name="bankName" value="${escapeHTML(bank.bankName)}" ${lock}></div>
    <div class="form-field"><label for="bank-branch">Branch</label><input id="bank-branch" name="bankBranch" value="${escapeHTML(bank.branch)}" ${lock}></div>
    <div class="form-field"><label for="bank-account">Account number</label><input id="bank-account" name="bankAccountNumber" inputmode="numeric" autocomplete="off" maxlength="22" value="${escapeHTML(bank.accountNumber)}" ${lock}></div>
    <div class="form-field"><label for="bank-ifsc">IFSC code</label><input id="bank-ifsc" name="bankIfsc" maxlength="11" autocapitalize="characters" placeholder="e.g. HDFC0001234" value="${escapeHTML(bank.ifsc)}" ${lock}></div>
    <div class="form-field"><label for="bank-type">Account type</label><select id="bank-type" name="bankAccountType" ${lock ? "disabled" : ""}>${["Current", "Savings", "Overdraft / Cash credit"].map((type) => `<option${bank.accountType === type ? " selected" : ""}>${type}</option>`).join("")}</select></div>
    <div class="form-field"><label for="bank-upi">UPI ID (optional)</label><input id="bank-upi" name="bankUpiId" autocapitalize="none" placeholder="pharmacy@okhdfcbank" value="${escapeHTML(bank.upiId)}" ${lock}></div>
  </div>`, "Save pharmacy profile", (data) => {
    const gstin = data.gstin.trim().toUpperCase();
    if (gstin && !/^\d{2}[A-Z]{5}\d{4}[A-Z]\dZ[A-Z0-9]$/.test(gstin)) return toast("Enter a valid 15-character GSTIN or leave the field blank.");
    const invoicePrefix = data.invoicePrefix.trim().toUpperCase();
    if (!/^[A-Z0-9-]{1,8}$/.test(invoicePrefix)) return toast("Invoice prefix must use 1–8 letters, numbers or hyphens.");
    const { bankAccountHolder, bankName, bankBranch, bankAccountNumber, bankIfsc, bankAccountType, bankUpiId, ...profile } = data;
    let newBank = bank;
    if (isAdmin) {
      newBank = {
        accountHolder: (bankAccountHolder || "").trim(), bankName: (bankName || "").trim(), branch: (bankBranch || "").trim(),
        accountNumber: (bankAccountNumber || "").replace(/\s+/g, ""), ifsc: (bankIfsc || "").trim().toUpperCase(),
        accountType: bankAccountType || "Current", upiId: (bankUpiId || "").trim()
      };
      if (newBank.accountNumber && !/^\d{9,18}$/.test(newBank.accountNumber)) return toast("Account number must be 9 to 18 digits.");
      if (newBank.ifsc && !/^[A-Z]{4}0[A-Z0-9]{6}$/.test(newBank.ifsc)) return toast("IFSC must be 11 characters, e.g. HDFC0001234.");
      if (newBank.upiId && !/^[A-Za-z0-9.\-_]{2,64}@[A-Za-z0-9]{2,64}$/.test(newBank.upiId)) return toast("Enter a valid UPI ID, e.g. pharmacy@okhdfcbank.");
      if (newBank.accountNumber && (!newBank.accountHolder || !newBank.bankName || !newBank.ifsc)) return toast("Enter the account holder, bank name and IFSC along with the account number.");
    }
    state.store = { ...state.store, ...profile, name: profile.name.trim(), city: profile.city.trim(), state: profile.state.trim(), gstin, bank: newBank };
    state.store.invoicePrefix = invoicePrefix;
    persist(); modalRoot.innerHTML = ""; render(); toast("Pharmacy invoice profile updated.");
  });
}

function showAdjustPoints(customerId) {
  const customer = customerById(customerId);
  if (!customer) return;
  openModal("Adjust points", `Update the rewards balance for ${escapeHTML(customer.name)}.`, `<div class="form-grid">
    <div class="form-field full"><label for="point-change">Points to add or remove</label><input id="point-change" name="amount" type="number" step="1" required placeholder="e.g. 25 or -10"></div>
    <div class="form-field full"><label for="point-reason">Reason</label><select id="point-reason" name="reason"><option>Manual adjustment</option><option>Purchase reward</option><option>Service recovery</option><option>Points correction</option></select></div>
  </div>`, "Update points", (data) => {
    const amount = Number(data.amount);
    if (!Number.isInteger(amount) || !amount) return toast("Enter a non-zero whole number of points.");
    if (customer.points + amount < 0) return toast("A customer's points balance cannot be negative.");
    customer.points += amount; persist(); modalRoot.innerHTML = ""; render(); toast(`${amount > 0 ? "+" : ""}${amount} points: ${data.reason}.`);
  });
}

function showRewardSettings() {
  openModal("Rewards program settings", "Set how members earn and redeem their points.", `<div class="form-grid">
    <div class="form-field"><label for="rule-earn">Points earned per ₹</label><input id="rule-earn" name="pointsPerRupee" type="number" min="1" max="10" value="${state.rules.pointsPerRupee}" required></div>
    <div class="form-field"><label for="rule-spend">For every spend (₹)</label><input id="rule-spend" name="earnPer" type="number" min="1" value="${state.rules.earnPer}" required></div>
    <div class="form-field full"><label for="rule-max">Maximum bill redemption (%)</label><input id="rule-max" name="redeemMaxPercent" type="number" min="1" max="100" value="${state.rules.redeemMaxPercent}" required></div>
  </div>`, "Save settings", (data) => {
    const percent = Number(data.redeemMaxPercent);
    if (percent < 1 || percent > 100) return toast("Redemption limit must be between 1% and 100%.");
    state.rules.pointsPerRupee = Number(data.pointsPerRupee);
    state.rules.earnPer = Number(data.earnPer);
    state.rules.redeemMaxPercent = percent;
    persist(); modalRoot.innerHTML = ""; render(); toast("Rewards program settings updated.");
  });
}

function showOfferDialog() {
  openModal("Create a store offer", "Add a discount rule for your in-store team.", `<div class="form-grid">
    <div class="form-field full"><label for="offer-name">Offer name</label><input id="offer-name" name="name" required placeholder="e.g. Weekend wellness"></div>
    <div class="form-field"><label for="offer-discount">Discount</label><input id="offer-discount" name="discount" type="number" min="1" max="100" value="10" required></div>
    <div class="form-field"><label for="offer-type">Discount type</label><select id="offer-type" name="type"><option value="percent">Percent off</option><option value="fixed">Rupees off</option></select></div>
    <div class="form-field full"><label for="offer-end">Valid until</label><input id="offer-end" name="end" type="date" min="${isoDate(new Date())}" required></div>
  </div>`, "Save offer", (data) => {
    const discount = Number(data.discount);
    if (discount > (data.type === "percent" ? 100 : 100000)) return toast("Enter a valid discount.");
    state.offers.unshift({ id: `o${Date.now()}`, name: data.name.trim(), discount, type: data.type, end: data.end, enabled: true });
    persist(); modalRoot.innerHTML = ""; render(); toast(`Offer "${data.name.trim()}" saved for your team.`);
  });
}

function invoiceMarkup(transaction, lines, totals, customer) {
  const isIntraState = !customer?.state || customer.state.trim().toLowerCase() === state.store.state.trim().toLowerCase();
  const halfTax = totals.tax / 2;
  const lineRows = lines.map((line) => {
    const lineSubtotal = line.qty * line.price;
    const lineDiscount = totals.subtotal ? totals.discount * lineSubtotal / totals.subtotal : 0;
    const lineTaxable = lineSubtotal - lineDiscount;
    const lineTax = lineTaxable * line.gst / 100;
    const taxDetails = isIntraState ? `CGST ${line.gst / 2}%<br>SGST ${line.gst / 2}%` : `IGST ${line.gst}%`;
    return `<tr><td>${escapeHTML(line.name)}<br>HSN ${escapeHTML(line.hsn)} · Batch ${escapeHTML(line.batch)} · Exp ${fmtDate(line.expiry)}</td><td>${line.qty}</td><td>${money(line.price)}</td><td>${taxDetails}</td><td>${money(lineTaxable + lineTax)}</td></tr>`;
  }).join("");
  const store = state.store;
  const storeAddress = [store.address, store.city, store.state, store.pincode].filter(Boolean).map(escapeHTML).join(", ");
  const invoiceTitle = store.gstin ? "TAX INVOICE" : "DEMO BILL · GSTIN NOT SET";
  return `<div class="invoice"><div class="invoice-brand"><div><b>${escapeHTML(store.name)}</b><div>${storeAddress || "Business address not configured"}</div><div>GSTIN: ${escapeHTML(store.gstin || "Not configured")} · Drug licence: ${escapeHTML(store.drugLicense || "Not configured")}</div>${store.phone ? `<div>Phone: ${escapeHTML(store.phone)}</div>` : ""}</div><span>${invoiceTitle}</span></div>
    <div class="invoice-meta"><span><b>Invoice</b><br>${escapeHTML(transaction.id)}</span><span><b>Date</b><br>${fmtDate(transaction.date)}</span><span><b>Customer</b><br>${escapeHTML(customer?.name || "Walk-in customer")}${customer?.address ? `<br>${escapeHTML(customer.address)}` : ""}${customer?.state ? `<br>${escapeHTML(customer.state)}` : ""}${customer?.gstin ? `<br>GSTIN: ${escapeHTML(customer.gstin)}` : ""}${customer?.drugLicense ? `<br>Drug licence: ${escapeHTML(customer.drugLicense)}` : ""}</span><span><b>Payment</b><br>${escapeHTML(transaction.payment)}${transaction.gateway ? `<br>${escapeHTML(transaction.gateway)}${transaction.phonepeTransactionId ? `<br>Txn: ${escapeHTML(transaction.phonepeTransactionId)}` : ""}` : ""}${transaction.soldBy ? `<br>Billed by: ${escapeHTML(transaction.soldBy.name)} (@${escapeHTML(transaction.soldBy.username)})` : ""}</span></div>
    <div class="table-wrap"><table class="invoice-lines"><thead><tr><th>ITEM / BATCH / HSN</th><th>QTY</th><th>RATE</th><th>TAX SPLIT</th><th>AMOUNT</th></tr></thead><tbody>${lineRows}</tbody></table></div>
    <div class="invoice-total">Taxable value after discount &nbsp; ${money(totals.taxable)}<br>${isIntraState ? `CGST &nbsp; ${money(halfTax)}<br>SGST &nbsp; ${money(halfTax)}` : `IGST &nbsp; ${money(totals.tax)}`}<br>Points redeemed &nbsp; −${money(totals.redeem)}<br><strong>Net payable &nbsp; ${money(totals.total)}</strong><br>    <span>${isIntraState ? "Intra-state tax split" : "Inter-state IGST"} shown for demonstration · Verify tax setup before use.</span></div>${bankMarkup(store.bank)}</div>`;
}

    function bankMarkup(bank) {
      if (!bank || !(bank.accountNumber || bank.upiId)) return "";
      const rows = [["Account name", bank.accountHolder], ["Bank", [bank.bankName, bank.branch].filter(Boolean).join(", ")], ["Account no.", bank.accountNumber], ["IFSC", bank.ifsc], ["Type", bank.accountNumber ? bank.accountType : ""], ["UPI", bank.upiId]];
      return `<div class="invoice-bank"><b>Pay to</b>${rows.filter(([, value]) => value).map(([label, value]) => `<div><span>${label}</span> ${escapeHTML(value)}</div>`).join("")}</div>`;
    }

async function startPhonePeCheckout(transaction, lines) {
  if (!phonepeConfigured) {
    toast("PhonePe sandbox is not configured. Add your PhonePe credentials to .env and restart Phoebix.");
    return;
  }
  document.querySelector(".app-shell").inert = true;
  setDatabaseStatus("saving", "Creating a secure PhonePe checkout");
  try {
    const merchantOrderId = `PHX${Date.now()}${crypto.randomUUID().replaceAll("-", "").slice(0, 12)}`;
    const response = await fetch("/api/payments/phonepe/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify({
        merchantOrderId,
        amount: Math.round(transaction.total * 100),
        expectedRevision: databaseRevision,
        intent: { transaction, lines }
      })
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `PhonePe checkout could not be started (HTTP ${response.status}).`);
    location.assign(result.redirectUrl);
  } catch (error) {
    console.error("Could not start PhonePe checkout.", error);
    document.querySelector(".app-shell").inert = false;
    setDatabaseStatus("connected", "Connected to the Phoebix SQLite database");
    toast(error.message);
  }
}

async function processPhonePeReturn() {
  const url = new URL(location.href);
  if (url.searchParams.get("phonepe") !== "return") return;
  const merchantOrderId = url.searchParams.get("merchantOrderId");
  if (!merchantOrderId) {
    toast("PhonePe returned without an order reference. Check the PhonePe dashboard.");
    return;
  }
  document.querySelector(".app-shell").inert = true;
  setDatabaseStatus("saving", "Verifying PhonePe payment with the server");
  try {
    const response = await fetch("/api/payments/phonepe/complete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify({ merchantOrderId })
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `PhonePe verification failed (HTTP ${response.status}).`);
    if (result.status === "PENDING") {
      document.querySelector(".app-shell").inert = false;
      setDatabaseStatus("connected", "Payment is still pending at PhonePe");
      toast("Payment is still being confirmed. Refresh this page to check again.");
      return;
    }
    if (result.status === "COMPLETED") {
      const stateResponse = await fetch("/api/state", { cache: "no-store" });
      if (!stateResponse.ok) throw new Error(`Could not reload the saved sale (HTTP ${stateResponse.status}).`);
      const saved = await stateResponse.json();
      state = normalizeState(saved.state);
      databaseRevision = saved.revision;
      invoiceSequence = state.transactions.reduce((highest, entry) => Math.max(highest, Number(entry.id.match(/\d+$/)?.[0] || 0)), 1048) + 1;
      history.replaceState({}, "", `${url.pathname}${url.hash}`);
      setDatabaseStatus("connected", "PhonePe payment verified and sale saved in SQLite");
      document.querySelector(".app-shell").inert = false;
      render();
      toast(`PhonePe payment verified. Invoice ${result.transaction.id} saved.`);
      return;
    }
    history.replaceState({}, "", `${url.pathname}${url.hash}`);
    document.querySelector(".app-shell").inert = false;
    setDatabaseStatus("connected", "Connected to the Phoebix SQLite database");
    toast(result.message || `PhonePe order status: ${result.status}. No sale was recorded.`);
  } catch (error) {
    console.error("Could not verify the PhonePe payment.", error);
    document.querySelector(".app-shell").inert = false;
    setDatabaseStatus("error", error.message);
    toast(error.message);
  }
}

function checkout() {
  if (!cart.length) return toast("Add a product before checking out.");
  const totals = cartTotals();
  if (totals.total <= 0) return toast("The payable amount must be greater than zero.");
  const customer = customerById(selectedCustomer);
  if (customer && totals.redeem > customer.points) return toast("This customer does not have enough points to redeem.");
  if (cart.some((line) => {
    const batch = batchById(productById(line.id), line.batchId);
    return !batch || isExpired(batch) || batch.stock < line.qty;
  })) return toast("A selected batch is expired or no longer has enough stock.");
  const transaction = { id: `${state.store.invoicePrefix}-${invoiceSequence++}`, customerId: customer?.id || null, customerName: customer?.name || "Walk-in customer", date: isoDate(new Date()), total: Math.round(totals.total * 100) / 100, items: cart.reduce((sum, line) => sum + line.qty, 0), payment: paymentMethod, status: paymentMethod === "Credit" ? "Credit" : "Paid", soldBy: { userId: currentUser.id, username: currentUser.username, name: currentUser.name } };
  const lines = cart.map((line) => ({ ...line }));
  transaction.lines = lines;
  transaction.totals = { ...totals };
  transaction.earned = customer ? Math.floor((totals.subtotal - totals.discount) / state.rules.earnPer) * state.rules.pointsPerRupee : 0;
  transaction.redeemed = totals.redeem;
  if (paymentMethod === "UPI" || paymentMethod === "Card") {
    transaction.gateway = "PhonePe";
    startPhonePeCheckout(transaction, lines);
    return;
  }
  lines.forEach((line) => {
    const product = productById(line.id);
    const batch = batchById(product, line.batchId);
    batch.stock -= line.qty;
    syncProductStock(product);
  });
  if (customer) {
    customer.points -= totals.redeem;
    customer.points += transaction.earned;
    customer.spent += totals.total;
    customer.visits += 1;
    customer.tier = customer.spent >= 10000 ? "Gold" : customer.spent >= 5000 ? "Silver" : "Member";
  }
  state.transactions.unshift(transaction);
  persist();
  const modalContent = invoiceMarkup(transaction, lines, totals, customer);
  cart = []; discountInput = 0; redeemInput = 0; selectedCustomer = ""; selectedOfferId = ""; paymentMethod = "Cash";
  render();
  document.body.classList.add("printing-invoice");
  openModal("Sale complete", `${transaction.id} · GST invoice is ready.`, `${modalContent}`, "Print invoice", () => { window.print(); });
  toast(`Sale saved. ${transaction.earned ? `${transaction.earned} loyalty points earned.` : "Stock updated."}`);
}

function printTransaction(transactionId) {
  const transaction = state.transactions.find((entry) => entry.id === transactionId);
  if (!transaction) return toast("Invoice details are not available in this demo record.");
  if (!transaction.lines || !transaction.totals) return toast("This sample invoice predates item-level history. New bills can be reprinted.");
  document.body.classList.add("printing-invoice");
  const customer = customerById(transaction.customerId);
  openModal("Invoice", `${transaction.id} · GST invoice`, invoiceMarkup(transaction, transaction.lines, transaction.totals, customer), "Print invoice", () => { window.print(); });
}

function csvDownload(filename, rows) {
  const csv = rows.map((row) => row.map((field) => `"${String(field ?? "").replace(/"/g, '""')}"`).join(",")).join("\r\n");
  const blob = new Blob(["\ufeff", csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url; link.download = filename; link.click();
  URL.revokeObjectURL(url);
  toast(`${filename} downloaded.`);
}

function exportInventory() {
  csvDownload("phoebix-inventory.csv", [["Product","Brand / pack","Batch","HSN","Expiry","Batch stock","Total product stock","Reorder at","Selling price INR","MRP INR","GST %"], ...state.products.flatMap((product)=>product.batches.map((batch)=>[product.name,product.brand,batch.batch,product.hsn,batch.expiry,batch.stock,product.stock,product.reorder,product.price,product.mrp,product.gst]))]);
}
function exportCustomers() {
  csvDownload("phoebix-customers.csv", [["Name","Phone","Email","Billing address","State / UT","GSTIN","Drug licence","Points","Tier","Lifetime spend INR","Visits","Joined"], ...state.customers.map((customer)=>[customer.name,customer.phone,customer.email,customer.address,customer.state,customer.gstin,customer.drugLicense,customer.points,customer.tier,customer.spent,customer.visits,customer.joined])]);
}
function exportReport() {
  csvDownload("phoebix-sales.csv", [["Invoice","Date","Customer","Items","Payment","Status","Total INR","Sold by (login ID)"], ...state.transactions.map((transaction)=>[transaction.id,transaction.date,transaction.customerName,transaction.items,transaction.payment,transaction.status,transaction.total,transaction.soldBy?.username||""])]);
}

document.addEventListener("click", (event) => {
  const nav = event.target.closest("[data-page]");
  if (nav) { event.preventDefault(); setPage(nav.dataset.page); return; }
  const target = event.target.closest("[data-action]");
  if (!target) return;
  const { action, id } = target.dataset;
  if (action === "close-modal" && target.classList.contains("modal-backdrop") && event.target !== target) return;
  if (action === "close-modal" && modalRoot.querySelector(".modal-locked")) return;
  if (action === "close-modal") { modalRoot.innerHTML = ""; document.body.classList.remove("printing-invoice"); return; }
  if (action === "add-stock") { showAddProduct(); return; }
  if (action === "receive-stock") { showReceiveStock(id, target.dataset.batch); return; }
  if (action === "add-customer") { showAddCustomer(); return; }
  if (action === "logout") { signOut(); return; }
  if (action === "add-user") { showAddUser(); return; }
  if (action === "edit-user") { showEditUser(id); return; }
  if (action === "add-sale-customer") { showAddCustomer((customer) => { selectedCustomer = customer.id; redeemInput = 0; }); return; }
  if (action === "adjust-points") { showAdjustPoints(id); return; }
  if (action === "edit-rules") { showRewardSettings(); return; }
  if (action === "new-offer") { showOfferDialog(); return; }
  if (action === "toggle-rule") { state.rules[target.dataset.rule] = !state.rules[target.dataset.rule]; persist(); render(); return; }
  if (action === "toggle-offer") {
    const offer = state.offers.find((entry) => entry.id === id);
    if (offer) { offer.enabled = !offer.enabled; if (!offer.enabled && selectedOfferId === id) selectedOfferId = ""; persist(); render(); }
    return;
  }
  if (action === "pos-category") { posCategory = target.dataset.category; renderSales(); return; }
  if (action === "add-to-cart") {
    const product = productById(id);
    if (!product) return;
    const batch = [...product.batches].sort((a, b) => a.expiry.localeCompare(b.expiry)).find((candidate) => {
      const reserved = cart.filter((entry) => entry.id === id && entry.batchId === candidate.id).reduce((sum, entry) => sum + entry.qty, 0);
      return candidate.stock > reserved && !isExpired(candidate);
    });
    if (!batch) return toast("No unexpired batch stock is available.");
    const line = cart.find((entry) => entry.id === id && entry.batchId === batch.id);
    if (line) line.qty += 1;
    else cart.push({ id: product.id, batchId: batch.id, name: product.name, batch: batch.batch, expiry: batch.expiry, hsn: product.hsn, price: product.price, gst: product.gst, qty: 1 });
    renderSales(); return;
  }
  if (action === "qty-minus" || action === "qty-plus") {
    const batchId = target.dataset.batch;
    const line = cart.find((entry) => entry.id === id && entry.batchId === batchId);
    const product = productById(id);
    const batch = batchById(product, batchId);
    if (line && action === "qty-minus") { line.qty -= 1; if (line.qty <= 0) cart = cart.filter((entry) => entry.id !== id || entry.batchId !== batchId); }
    if (line && action === "qty-plus" && batch && !isExpired(batch) && batch.stock > line.qty) line.qty += 1;
    else if (line && action === "qty-plus") toast("No more unexpired units are available in this batch.");
    renderSales(); return;
  }
  if (action === "checkout") { checkout(); return; }
  if (action === "export-inventory") { exportInventory(); return; }
  if (action === "export-customers") { exportCustomers(); return; }
  if (action === "export-report") { exportReport(); return; }
  if (action === "print-invoice") { printTransaction(id); return; }
});

document.addEventListener("input", (event) => {
  if (event.target.id === "inventory-search") {
    const cursor = event.target.selectionStart;
    renderInventory();
    const input = document.getElementById("inventory-search");
    input.focus(); input.setSelectionRange(cursor, cursor);
  }
  if (event.target.id === "customer-search") {
    customerFilter = event.target.value;
    const cursor = event.target.selectionStart;
    renderCustomers();
    const input = document.getElementById("customer-search");
    input.focus(); input.setSelectionRange(cursor, cursor);
  }
  if (event.target.id === "pos-search") {
    posSearch = event.target.value;
    const cursor = event.target.selectionStart;
    renderSales();
    const input = document.getElementById("pos-search");
    input.focus(); input.setSelectionRange(cursor, cursor);
  }
});

document.addEventListener("change", (event) => {
  if (event.target.id === "inventory-filter") { inventoryFilter = event.target.value; renderInventory(); }
  if (event.target.id === "sale-customer") { selectedCustomer = event.target.value; redeemInput = 0; renderSales(); }
  if (event.target.id === "customer-tier-filter") { customerTierFilter = event.target.value; renderCustomers(); }
  if (event.target.id === "discount-type") { discountType = event.target.value; renderSales(); }
  if (event.target.id === "sale-offer") { selectedOfferId = event.target.value; renderSales(); }
  if (event.target.id === "payment-method") { paymentMethod = event.target.value; renderSales(); }
  if (event.target.id === "discount-input") { discountInput = Math.max(0, Number(event.target.value)); refreshCartSummary(); }
  if (event.target.id === "redeem-input") { redeemInput = Math.max(0, Number(event.target.value)); refreshCartSummary(); }
});

document.getElementById("mobile-menu").addEventListener("click", () => document.getElementById("sidebar").classList.toggle("open"));
document.getElementById("global-search").addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    const query = event.currentTarget.value.trim();
    if (query) { posSearch = query; setPage("sales"); document.getElementById("pos-search")?.focus(); }
  }
});
document.getElementById("settings-button").addEventListener("click", (event) => { event.preventDefault(); showStoreSettings(); });
document.getElementById("help-button").addEventListener("click", () => toast("Help centre is not connected."));
document.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); document.getElementById("global-search").focus(); }
  if (event.key === "Escape" && !modalRoot.querySelector(".modal-locked")) { modalRoot.innerHTML = ""; document.getElementById("sidebar").classList.remove("open"); }
});
document.getElementById("account-button").addEventListener("click", () => showChangePassword(false));
document.getElementById("today-label").textContent = today.toLocaleDateString("en-IN", { weekday: "short", day: "2-digit", month: "short", year: "numeric" });
bootstrapSession();

if ("serviceWorker" in navigator && (location.protocol === "https:" || location.hostname === "localhost" || location.hostname === "127.0.0.1")) {
  navigator.serviceWorker.register("./sw.js").catch((error) => console.error("Could not register the offline app shell.", error));
}
