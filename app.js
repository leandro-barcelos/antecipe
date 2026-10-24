const http = require('http');

const servidor = http.createServer((req, res) => {
    res.statusCode = 200;
    res.setHeader('Content-Type', 'text/plain; charset=utf-8');
    res.end('Olá! O meu servidor Node.js está a funcionar perfeitamente.\n');
});

const PORTA = 3000;
servidor.listen(PORTA, () => {
    console.log(`Servidor a correr em http://localhost:${PORTA}/`);
});