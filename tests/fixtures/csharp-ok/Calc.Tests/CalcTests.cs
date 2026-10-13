using Xunit;

namespace Calc.Tests;

public class CalcTests
{
    [Fact]
    public void Add() => Assert.Equal(5, MathOps.Add(2, 3));
}
