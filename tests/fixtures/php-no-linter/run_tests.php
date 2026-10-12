<?php
require __DIR__ . '/calc.php';

if (add(2, 3) !== 5) {
    fwrite(STDERR, "FAIL: add(2, 3) = " . add(2, 3) . ", expected 5\n");
    exit(1);
}
echo "OK\n";
