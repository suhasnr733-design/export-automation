/**
 * API 3 - EXPORT AUTOMATION SYSTEM
 * Frontend Application Scripts
 */

document.addEventListener('DOMContentLoaded', () => {
  // 1. Table Search & Filtering Engine
  const searchInput = document.getElementById('tableSearch');
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      const term = e.target.value.toLowerCase().trim();
      const rows = document.querySelectorAll('.data-table tbody tr');
      rows.forEach((row) => {
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(term) ? '' : 'none';
      });
    });
  }

  // 2. Select Filter (Country / Category / Status)
  const categoryFilter = document.getElementById('categoryFilter');
  if (categoryFilter) {
    categoryFilter.addEventListener('change', (e) => {
      const filterVal = e.target.value.toLowerCase();
      const rows = document.querySelectorAll('.data-table tbody tr');
      rows.forEach((row) => {
        const cat = row.getAttribute('data-category') || '';
        if (!filterVal || filterVal === 'all' || cat.toLowerCase() === filterVal) {
          row.style.display = '';
        } else {
          row.style.display = 'none';
        }
      });
    });
  }

  // 3. Modal Controllers
  window.openModal = function (modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
      modal.classList.add('active');
    }
  };

  window.closeModal = function (modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
      modal.classList.remove('active');
    }
  };

  // Close modals when clicking on backdrop
  document.querySelectorAll('.modal-backdrop').forEach((backdrop) => {
    backdrop.addEventListener('click', (e) => {
      if (e.target === backdrop) {
        backdrop.classList.remove('active');
      }
    });
  });

  // 4. Auto-dismiss flash alerts after 6 seconds
  setTimeout(() => {
    document.querySelectorAll('.flash-message').forEach((flash) => {
      flash.style.transition = 'opacity 0.5s ease';
      flash.style.opacity = '0';
      setTimeout(() => flash.remove(), 500);
    });
  }, 6000);
});
