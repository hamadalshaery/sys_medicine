const cartItemsElement = document.getElementById('cart-items');
const checkoutButton = document.getElementById('checkout-button');
const cartSummary = document.getElementById('cart-summary');
const paymentSelect = document.getElementById('payment-method');
const pharmacyInput = document.getElementById('pharmacy');
let cart = JSON.parse(localStorage.getItem('pharmacy_cart') || '[]');

function saveCart() {
  localStorage.setItem('pharmacy_cart', JSON.stringify(cart));
  renderCart();
}

function renderCart() {
  cartItemsElement.innerHTML = '';
  if (!cart.length) {
    cartItemsElement.innerHTML = '<p class="text-slate-500">السلة فارغة.</p>';
    cartSummary.textContent = '';
    return;
  }

  let subtotal = 0;
  cart.forEach((item, index) => {
    subtotal += item.unit_price * item.quantity;
    const row = document.createElement('div');
    row.className = 'flex justify-between items-center gap-3 p-3 rounded-xl border border-slate-200';
    row.innerHTML = `
      <div>
        <h3 class="font-semibold">${item.name}</h3>
        <p class="text-slate-500 text-sm">${item.quantity} × ${item.unit_price} د</p>
      </div>
      <div class="flex items-center gap-2">
        <button class="px-3 py-1 rounded bg-slate-100" onclick="decrease(${index})">-</button>
        <button class="px-3 py-1 rounded bg-slate-100" onclick="increase(${index})">+</button>
        <button class="px-3 py-1 rounded bg-rose-500 text-white" onclick="removeItem(${index})">حذف</button>
      </div>
    `;
    cartItemsElement.appendChild(row);
  });

  cartSummary.innerHTML = `
    <p class="font-semibold">إجمالي السلة: ${subtotal.toFixed(2)} د</p>
  `;
}

function increase(index) {
  cart[index].quantity += 1;
  saveCart();
}

function decrease(index) {
  if (cart[index].quantity > 1) {
    cart[index].quantity -= 1;
  } else {
    cart.splice(index, 1);
  }
  saveCart();
}

function removeItem(index) {
  cart.splice(index, 1);
  saveCart();
}

window.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.add-to-cart').forEach(button => {
    button.addEventListener('click', () => {
      const item_code = button.dataset.code;
      const name = button.dataset.name;
      const category = button.dataset.category;
      const unit_price = Number(button.dataset.price || 0);
      const existing = cart.find(item => item.item_code === item_code);
      if (existing) {
        existing.quantity += 1;
      } else {
        cart.push({ item_code, name, category, quantity: 1, unit_price, original_price: unit_price });
      }
      saveCart();
    });
  });
  renderCart();
});

checkoutButton.addEventListener('click', async () => {
  if (!cart.length) {
    alert('السلة فارغة.');
    return;
  }

  const payload = {
    cart_items: cart,
    payment_method: paymentSelect.value,
    pharmacy: pharmacyInput.value,
  };

  const response = await fetch('/api/cart/checkout', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const error = await response.json();
    alert(error.detail || 'فشل إتمام الطلب');
    return;
  }

  const data = await response.json();
  alert('تم إنشاء الفاتورة بنجاح. يمكنك تنزيلها الآن.');
  window.location.href = data.pdf_url;
  localStorage.removeItem('pharmacy_cart');
  cart = [];
  renderCart();
});
