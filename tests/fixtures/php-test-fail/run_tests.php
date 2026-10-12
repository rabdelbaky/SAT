<?php
require __DIR__ . '/calc.php';

if (add(2, 3) !== 6) {
    fwrite(STDERR, "FAIL: add(2, 3) = " . add(2, 3) . ", expected 6\n");
    exit(1);
}
echo "OK\n";
