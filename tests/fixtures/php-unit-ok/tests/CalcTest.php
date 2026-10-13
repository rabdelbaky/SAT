<?php

declare(strict_types=1);

namespace App\Tests;

use App\Calc;
use PHPUnit\Framework\TestCase;

final class CalcTest extends TestCase
{
    public function testAdd(): void
    {
        $this->assertSame(5, Calc::add(2, 3));
    }
}
