const qrReaderElement = document.getElementById('qr-reader');
if (qrReaderElement) {
  const html5QrCode = new Html5Qrcode('qr-reader');
  html5QrCode.start(
    { facingMode: 'environment' },
    {
      fps: 10,
      qrbox: { width: 250, height: 250 }
    },
    async (decodedText) => {
      const response = await fetch(`/api/barcode-search?code=${encodeURIComponent(decodedText)}`);
      if (response.ok) {
        const item = await response.json();
        const found = confirm(`تم إيجاد المنتج: ${item.name} - السعر: ${item.price} د. أضف إلى السلة؟`);
        if (found) {
          const cart = JSON.parse(localStorage.getItem('pharmacy_cart') || '[]');
          const existing = cart.find(i => i.item_code === item.item_code);
          if (existing) {
            existing.quantity += 1;
          } else {
            cart.push({ item_code: item.item_code, name: item.name, category: item.category, quantity: 1, unit_price: item.price, original_price: item.price });
          }
          localStorage.setItem('pharmacy_cart', JSON.stringify(cart));
          alert('تمت الإضافة إلى السلة');
          window.location.reload();
        }
      }
    },
    (errorMessage) => {
      // ignore scanning errors
    }
  ).catch(err => {
    console.warn('QR start failed:', err);
  });
}
