/* Dos cosas:

   1. Mientras una imagen no esté cargada en assets/img/, la figura muestra un
      recuadro con el nombre de archivo que espera y una descripción de lo que
      debería mostrar. Al copiar el archivo con ese nombre, la imagen aparece
      sola y el recuadro desaparece.

   2. Cuando la imagen sí está, se puede abrir aparte en tamaño completo, con
      un rótulo que lo avisa. Los diagramas se leen mejor así. */

document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('figure .marco img').forEach(function (img) {

    function pendiente() {
      var marco = img.closest('.marco');
      if (!marco || marco.querySelector('.pendiente')) return;
      var nombre = (img.getAttribute('src') || '').split('/').pop();
      var caja = document.createElement('div');
      caja.className = 'pendiente';
      var b = document.createElement('b');
      b.textContent = nombre;
      caja.appendChild(b);
      caja.appendChild(document.createTextNode(img.alt || ''));
      img.remove();
      marco.appendChild(caja);
    }

    function ampliable() {
      var marco = img.closest('.marco');
      if (!marco || marco.querySelector('.lupa')) return;
      var a = document.createElement('a');
      a.href = img.getAttribute('src');
      a.target = '_blank';
      a.rel = 'noopener';
      a.title = 'Abrir la figura en tamaño completo';
      img.parentNode.insertBefore(a, img);
      a.appendChild(img);
      var lupa = document.createElement('span');
      lupa.className = 'lupa';
      lupa.textContent = 'Ampliar';
      marco.appendChild(lupa);
    }

    img.addEventListener('error', pendiente);
    img.addEventListener('load', ampliable);
    if (img.complete) { (img.naturalWidth === 0 ? pendiente : ampliable)(); }
  });
});
