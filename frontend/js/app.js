// ============================================================================
// Counter POS — frontend application logic
// Talks to the Flask API at API_BASE. No frameworks, just fetch + DOM.
// ============================================================================

const API_BASE = "http://localhost:5000/api";
const TAX_RATE = 8; // percent — adjust to your local tax rate

let state = {
    categories: [],
    products: [],
    cart: [],
    activeCategory: "",
    searchTerm: "",
    paymentMethod: "cash",
    session: null,
};

// ---------------------------------------------------------------- utilities
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);
const money = (n) => `$${Number(n || 0).toFixed(2)}`;

async function api(path, options = {}) {
    const url = `${API_BASE}${path}`;

    console.log("API REQUEST:", url);

    try {
        const res = await fetch(url, {
            ...options,
            headers: {
                "Content-Type": "application/json",
                ...(options.headers || {}),
            },
        });

        console.log("API RESPONSE:", res.status, url);

        const text = await res.text();

        let data = {};

        if (text) {
            try {
                data = JSON.parse(text);
            } catch (e) {
                console.error("Invalid JSON:", text);
                throw new Error(
                    `Invalid response from backend (${res.status})`
                );
            }
        }

        if (!res.ok) {
            throw new Error(
                data.error || `Request failed (${res.status})`
            );
        }

        return data;

    } catch (error) {
        console.error("API ERROR:", error);
        throw error;
    }
}

function openModal(id) { $(`#${id}`).classList.remove("hidden"); }
function closeModal(id) { $(`#${id}`).classList.add("hidden"); }

$$("[data-close]").forEach((btn) =>
  btn.addEventListener("click", () => closeModal(btn.dataset.close))
);

// ---------------------------------------------------------------- navigation
$$(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    $$(".nav-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    $$(".view").forEach((v) => v.classList.add("hidden"));
    $(`#view-${btn.dataset.view}`).classList.remove("hidden");

    if (btn.dataset.view === "orders") loadOrders();
    if (btn.dataset.view === "products") loadProductsTable();
    if (btn.dataset.view === "dashboard") loadDashboard();
  });
});

// ============================================================================
// REGISTER SESSION ("Counter") — open/close + 24h auto-lock
// ============================================================================

let currentSession = null;
let sessionTimerInterval = null;

async function initSession() {
    try {
        const session = await api("/sessions/current");

        console.log("CURRENT SESSION:", session);

        if (!session) {
            currentSession = null;
            state.session = null;

            openModal("openSessionModal");
            return;
        }

        currentSession = session;
        state.session = session;

        if (session.expired) {
            showLockScreen(session);
            return;
        }

        closeModal("openSessionModal");
        $("#lockOverlay").classList.add("hidden");

        startSessionTimer();

    } catch (err) {
        console.error("SESSION INIT FAILED:", err);

        alert(
            "Could not load counter session.\n\n" +
            err.message
        );
    }
}

function startSessionTimer() {
  if (sessionTimerInterval) clearInterval(sessionTimerInterval);
  updateSessionDisplay();
  sessionTimerInterval = setInterval(updateSessionDisplay, 1000);
}

function updateSessionDisplay() {
  if (!currentSession) return;
  const openedAt = new Date(currentSession.opened_at);
  const elapsedMs = Date.now() - openedAt.getTime();
  const maxMs = (currentSession.max_hours || 24) * 3600 * 1000;

  if (elapsedMs >= maxMs) {
    clearInterval(sessionTimerInterval);
    showLockScreen(currentSession);
    return;
  }

  const totalSeconds = Math.floor(elapsedMs / 1000);
  const h = String(Math.floor(totalSeconds / 3600)).padStart(2, "0");
  const m = String(Math.floor((totalSeconds % 3600) / 60)).padStart(2, "0");
  const s = String(totalSeconds % 60).padStart(2, "0");
  $("#sessionTimer").textContent = `${h}:${m}:${s}`;
  $("#sessionCashier").textContent = currentSession.cashier_name;
}

function showLockScreen(session) {
  const openedAt = new Date(session.opened_at);
  $("#lockSessionInfo").textContent = `${session.cashier_name} · opened ${openedAt.toLocaleString()}`;
  $("#lockOverlay").classList.remove("hidden");
}

$("#confirmOpenSessionBtn").addEventListener("click", async () => {

    const cashierName = $("#cashierNameInput").value.trim();
    const openingCash = Number($("#openingCashInput").value || 0);

    if (!cashierName) {
        alert("Please enter a cashier name.");
        return;
    }

    if (openingCash < 0) {
        alert("Opening cash cannot be negative.");
        return;
    }

    const btn = $("#confirmOpenSessionBtn");

    btn.disabled = true;

    try {

        const session = await api("/sessions", {
            method: "POST",
            body: JSON.stringify({
                cashier_name: cashierName,
                opening_cash: openingCash,
            }),
        });

        console.log("SESSION OPENED:", session);

        currentSession = session;
        state.session = session;

        closeModal("openSessionModal");

        $("#lockOverlay").classList.add("hidden");

        $("#cashierNameInput").value = "";
        $("#openingCashInput").value = "0";

        startSessionTimer();

    } catch (err) {

        console.error("OPEN SESSION ERROR:", err);

        alert(
            "Could not open counter.\n\n" +
            err.message
        );

    } finally {

        btn.disabled = false;
    }
});

async function closeCurrentSessionAndPromptReopen() {

    if (!currentSession) {
        openModal("openSessionModal");
        return;
    }

    const closingCashInput = prompt(
        `Closing cash for ${currentSession.cashier_name}\n\n` +
        `Expected cash: ${money(currentSession.expected_cash)}\n\n` +
        `Enter actual closing cash:`
    );

    if (closingCashInput === null) {
        return;
    }

    const closingCash = Number(closingCashInput);

    if (!Number.isFinite(closingCash) || closingCash < 0) {
        alert("Please enter a valid closing cash amount.");
        return;
    }

    try {

        const result = await api(
            `/sessions/${currentSession.id}/close`,
            {
                method: "POST",
                body: JSON.stringify({
                    closing_cash: closingCash
                })
            }
        );

        console.log("SESSION CLOSED:", result);

        alert(
            `Counter closed successfully.\n\n` +
            `Cashier: ${result.cashier_name}\n` +
            `Opening Cash: ${money(result.opening_cash)}\n` +
            `Cash Sales: ${money(result.cash_sales)}\n` +
            `Expected Cash: ${money(result.expected_cash)}\n` +
            `Closing Cash: ${money(result.closing_cash)}\n` +
            `Difference: ${money(result.difference)}`
        );

        currentSession = null;
        state.session = null;

        clearInterval(sessionTimerInterval);

        $("#lockOverlay").classList.add("hidden");

        openModal("openSessionModal");

    } catch (err) {

        console.error("CLOSE SESSION ERROR:", err);

        alert(
            "Could not close counter.\n\n" +
            err.message
        );
    }
}

$("#closeSessionBtn").addEventListener("click", () => {
  if (confirm("Close the current register session?")) closeCurrentSessionAndPromptReopen();
});

$("#lockCloseBtn").addEventListener("click", () => closeCurrentSessionAndPromptReopen());

// ============================================================================
// CATALOG (Register view)
// ============================================================================

async function loadCatalog() {
  const [categories, products] = await Promise.all([
    api("/categories"),
    api("/products"),
  ]);
  state.categories = categories;
  state.products = products;
  renderCategoryTabs();
  renderProductGrid();
}

function renderCategoryTabs() {
  const wrap = $("#categoryTabs");
  wrap.innerHTML = `<button class="cat-tab ${state.activeCategory === "" ? "active" : ""}" data-cat="">All items</button>`;
  state.categories.forEach((c) => {
    const btn = document.createElement("button");
    btn.className = `cat-tab ${state.activeCategory == c.id ? "active" : ""}`;
    btn.dataset.cat = c.id;
    btn.textContent = c.name;
    wrap.appendChild(btn);
  });
  wrap.querySelectorAll(".cat-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      state.activeCategory = tab.dataset.cat;
      renderCategoryTabs();
      renderProductGrid();
    });
  });
}

function renderProductGrid() {
  const grid = $("#productGrid");
  const term = state.searchTerm.trim().toLowerCase();
  const items = state.products.filter((p) => {
    const matchesCat = !state.activeCategory || String(p.category_id) === String(state.activeCategory);
    const matchesTerm = !term || p.name.toLowerCase().includes(term) || (p.sku || "").toLowerCase().includes(term);
    return matchesCat && matchesTerm;
  });

  if (!items.length) {
    grid.innerHTML = `<div class="ticket-empty">No products match.</div>`;
    return;
  }

  grid.innerHTML = "";
  items.forEach((p) => {
    const outOfStock = p.track_stock && p.stock <= 0;
    const card = document.createElement("button");
    card.className = "product-card";
    card.disabled = outOfStock;
    card.innerHTML = `
      <span class="product-emoji">${p.image_emoji || "🛒"}</span>
      <span class="product-name">${escapeHtml(p.name)}</span>
      <span class="product-meta">
        <span class="product-price">${money(p.price)}</span>
        <span class="product-stock">${p.track_stock ? (outOfStock ? "Out" : `${p.stock} left`) : ""}</span>
      </span>
    `;
    card.addEventListener("click", () => addToCart(p));
    grid.appendChild(card);
  });
}

$("#productSearch").addEventListener("input", (e) => {
  state.searchTerm = e.target.value;
  renderProductGrid();
});

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// ============================================================================
// CART / TICKET
// ============================================================================

function addToCart(product) {
  const existing = state.cart.find((i) => i.product_id === product.id);
  if (existing) {
    if (product.track_stock && existing.quantity >= product.stock) return;
    existing.quantity += 1;
  } else {
    state.cart.push({
      product_id: product.id,
      name: product.name,
      price: product.price,
      quantity: 1,
      stock: product.stock,
      track_stock: product.track_stock,
    });
  }
  renderCart();
}

function changeQty(productId, delta) {
  const line = state.cart.find((i) => i.product_id === productId);
  if (!line) return;
  line.quantity += delta;
  if (line.quantity <= 0) {
    state.cart = state.cart.filter((i) => i.product_id !== productId);
  } else if (line.track_stock && line.quantity > line.stock) {
    line.quantity = line.stock;
  }
  renderCart();
}

function removeLine(productId) {
  state.cart = state.cart.filter((i) => i.product_id !== productId);
  renderCart();
}

$("#clearCart").addEventListener("click", () => {
  state.cart = [];
  renderCart();
});

function cartTotals() {
  const subtotal = state.cart.reduce((sum, i) => sum + i.price * i.quantity, 0);
  const discount = Math.min(Number($("#discountInput").value || 0), subtotal);
  const taxable = Math.max(subtotal - discount, 0);
  const tax = (taxable * TAX_RATE) / 100;
  const total = taxable + tax;
  return { subtotal, discount, tax, total };
}

function renderCart() {
  const linesWrap = $("#cartLines");
  if (!state.cart.length) {
    linesWrap.innerHTML = `<div class="ticket-empty">No items yet — tap a product to add it.</div>`;
  } else {
    linesWrap.innerHTML = "";
    state.cart.forEach((line) => {
      const row = document.createElement("div");
      row.className = "cart-line";
      row.innerHTML = `
        <span class="cl-name">${escapeHtml(line.name)}</span>
        <span class="cl-price">${money(line.price)}</span>
        <span class="cl-qty">
          <button data-action="dec">–</button>
          <span>${line.quantity}</span>
          <button data-action="inc">+</button>
        </span>
        <span class="cl-total">${money(line.price * line.quantity)}</span>
        <button class="cl-remove" data-action="remove">×</button>
      `;
      row.querySelector('[data-action="inc"]').addEventListener("click", () => changeQty(line.product_id, 1));
      row.querySelector('[data-action="dec"]').addEventListener("click", () => changeQty(line.product_id, -1));
      row.querySelector('[data-action="remove"]').addEventListener("click", () => removeLine(line.product_id));
      linesWrap.appendChild(row);
    });
  }

  const { subtotal, discount, tax, total } = cartTotals();
  $("#sumSubtotal").textContent = money(subtotal);
  $("#sumTax").textContent = money(tax);
  $("#sumTotal").textContent = money(total);
  $("#taxRateLabel").textContent = TAX_RATE;
  $("#openCheckout").disabled = state.cart.length === 0;
}

$("#discountInput").addEventListener("input", renderCart);

// ============================================================================
// CHECKOUT
// ============================================================================

$("#openCheckout").addEventListener("click", () => {
  const { total } = cartTotals();
  $("#modalTotal").textContent = money(total);
  $("#amountTendered").value = total.toFixed(2);
  updateChangeDue();
  openModal("checkoutModal");
});

$$(".pay-method").forEach((btn) => {
  btn.addEventListener("click", () => {
    $$(".pay-method").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    state.paymentMethod = btn.dataset.method;
    $("#cashRow").style.display = state.paymentMethod === "cash" ? "block" : "none";
  });
});

$("#amountTendered").addEventListener("input", updateChangeDue);

function updateChangeDue() {
  const { total } = cartTotals();
  const tendered = Number($("#amountTendered").value || 0);
  const change = Math.max(tendered - total, 0);
  $("#changeDue").textContent = money(change);
}

$("#confirmChargeBtn").addEventListener("click", async () => {
  const { subtotal, discount, total } = cartTotals();
  const payload = {
    items: state.cart.map((i) => ({ product_id: i.product_id, name: i.name, price: i.price, quantity: i.quantity })),
    discount,
    tax_rate: TAX_RATE,
    payment_method: state.paymentMethod,
    customer_name: $("#customerNameInput").value || "Walk-in Customer",
    amount_tendered: state.paymentMethod === "cash" ? Number($("#amountTendered").value || total) : total,
  };

  try {
    const order = await api("/orders", { method: "POST", body: JSON.stringify(payload) });
    closeModal("checkoutModal");
    showReceipt(order);
    state.cart = [];
    $("#discountInput").value = 0;
    $("#customerNameInput").value = "";
    renderCart();
    loadCatalog(); // refresh stock counts
  } catch (err) {
    alert(`Could not complete sale: ${err.message}`);
  }
});

function showReceipt(order) {
  const lines = order.items
    .map((i) => `<div class="rline"><span>${escapeHtml(i.product_name)} ×${i.quantity}</span><span>${money(i.line_total)}</span></div>`)
    .join("");

  $("#receiptPaper").innerHTML = `
    <div class="rhead">Counter POS</div>
    <div class="rsub">Order ${order.order_number} · ${new Date(order.created_at).toLocaleString()}</div>
    <div class="rdivider"></div>
    ${lines}
    <div class="rdivider"></div>
    <div class="rline"><span>Subtotal</span><span>${money(order.subtotal)}</span></div>
    <div class="rline"><span>Discount</span><span>-${money(order.discount)}</span></div>
    <div class="rline"><span>Tax</span><span>${money(order.tax)}</span></div>
    <div class="rdivider"></div>
    <div class="rline rtotal"><span>Total</span><span>${money(order.total)}</span></div>
    <div class="rline"><span>Paid via</span><span>${order.payment_method}</span></div>
    ${order.payment_method === "cash" ? `<div class="rline"><span>Change</span><span>${money(order.change_due)}</span></div>` : ""}
  `;
  openModal("receiptModal");
}

// ============================================================================
// ORDERS VIEW
// ============================================================================

async function loadOrders() {
  const dateVal = $("#ordersDateFilter").value;
  const orders = await api(`/orders${dateVal ? `?date=${dateVal}` : ""}`);
  const tbody = $("#ordersTableBody");
  if (!orders.length) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:30px;">No orders yet.</td></tr>`;
    return;
  }
  tbody.innerHTML = orders
    .map(
      (o) => `
      <tr>
        <td class="mono">${o.order_number}</td>
        <td>${new Date(o.created_at).toLocaleString()}</td>
        <td>${escapeHtml(o.customer_name)}</td>
        <td>—</td>
        <td><span class="pill">${o.payment_method}</span></td>
        <td class="mono">${money(o.total)}</td>
      </tr>`
    )
    .join("");
}

$("#ordersDateFilter").addEventListener("change", loadOrders);

// ============================================================================
// PRODUCTS VIEW (management)
// ============================================================================

async function loadProductsTable() {
  const products = await api("/products");
  state.products = products;
  const tbody = $("#productsTableBody");
  tbody.innerHTML = products
    .map(
      (p) => `
      <tr>
        <td>${p.image_emoji || "🛒"}</td>
        <td>${escapeHtml(p.name)}</td>
        <td class="mono">${p.sku || "—"}</td>
        <td>${escapeHtml(p.category_name || "Uncategorized")}</td>
        <td class="mono">${money(p.price)}</td>
        <td class="mono">${p.track_stock ? p.stock : "—"}</td>
        <td style="text-align:right;">
          <button class="icon-btn" data-edit="${p.id}">✎</button>
          <button class="icon-btn" data-delete="${p.id}">✕</button>
        </td>
      </tr>`
    )
    .join("");

  tbody.querySelectorAll("[data-edit]").forEach((btn) =>
    btn.addEventListener("click", () => openProductModal(Number(btn.dataset.edit)))
  );
  tbody.querySelectorAll("[data-delete]").forEach((btn) =>
    btn.addEventListener("click", async () => {
      if (!confirm("Remove this product?")) return;
      await api(`/products/${btn.dataset.delete}`, { method: "DELETE" });
      loadProductsTable();
    })
  );
}

async function populateCategorySelect() {
  const select = $("#productCategory");
  const categories = await api("/categories");
  select.innerHTML = categories.map((c) => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join("");
}

function openProductModal(id) {
  populateCategorySelect().then(() => {
    if (id) {
      const p = state.products.find((x) => x.id === id);
      $("#productModalTitle").textContent = "Edit product";
      $("#productId").value = p.id;
      $("#productName").value = p.name;
      $("#productCategory").value = p.category_id || "";
      $("#productPrice").value = p.price;
      $("#productSku").value = p.sku || "";
      $("#productStock").value = p.stock;
      $("#productEmoji").value = p.image_emoji || "🛒";
    } else {
      $("#productModalTitle").textContent = "New product";
      $("#productId").value = "";
      $("#productName").value = "";
      $("#productPrice").value = "";
      $("#productSku").value = "";
      $("#productStock").value = 0;
      $("#productEmoji").value = "🛒";
    }
    openModal("productModal");
  });
}

$("#newProductBtn").addEventListener("click", () => openProductModal(null));

$("#saveProductBtn").addEventListener("click", async () => {
  const id = $("#productId").value;
  const payload = {
    name: $("#productName").value.trim(),
    category_id: Number($("#productCategory").value) || null,
    price: Number($("#productPrice").value || 0),
    sku: $("#productSku").value.trim(),
    stock: Number($("#productStock").value || 0),
    track_stock: 1,
    image_emoji: $("#productEmoji").value || "🛒",
  };
  if (!payload.name || payload.price <= 0) {
    alert("Please provide a name and a price greater than 0.");
    return;
  }
  try {
    if (id) {
      await api(`/products/${id}`, { method: "PUT", body: JSON.stringify(payload) });
    } else {
      await api("/products", { method: "POST", body: JSON.stringify(payload) });
    }
    closeModal("productModal");
    loadProductsTable();
    loadCatalog();
  } catch (err) {
    alert(`Could not save product: ${err.message}`);
  }
});

// ============================================================================
// DASHBOARD
// ============================================================================

async function loadDashboard() {
  const dateInput = $("#dashDateFilter");
  if (!dateInput.value) dateInput.value = new Date().toISOString().slice(0, 10);
  const summary = await api(`/reports/summary?date=${dateInput.value}`);

  $("#statSales").textContent = money(summary.total_sales);
  $("#statOrders").textContent = summary.order_count;
  $("#statTax").textContent = money(summary.total_tax);
  $("#statDiscount").textContent = money(summary.total_discount);

  $("#topItemsList").innerHTML = summary.top_items.length
    ? summary.top_items
        .map(
          (i) => `<div class="top-item-row"><span class="ti-name">${escapeHtml(i.product_name)}</span><span class="ti-meta">${i.qty} sold · ${money(i.revenue)}</span></div>`
        )
        .join("")
    : `<div class="ticket-empty">No sales yet today.</div>`;

  $("#paymentBreakdown").innerHTML = summary.payment_breakdown.length
    ? summary.payment_breakdown
        .map(
          (i) => `<div class="top-item-row"><span class="ti-name">${escapeHtml(i.payment_method)}</span><span class="ti-meta">${i.count} orders · ${money(i.total)}</span></div>`
        )
        .join("")
    : `<div class="ticket-empty">No sales yet today.</div>`;
}

$("#dashDateFilter").addEventListener("change", loadDashboard);

// ============================================================================
// INIT
// ============================================================================

loadCatalog().catch((err) => {
    console.error("CATALOG LOAD FAILED:", err);

    $("#productGrid").innerHTML = `
        <div class="ticket-empty">
            <strong>Could not load products.</strong><br>
            ${escapeHtml(err.message)}
            <br><br>
            API: ${API_BASE}
        </div>
    `;
});
renderCart();
initSession().catch((err) => console.error("Session init failed:", err));