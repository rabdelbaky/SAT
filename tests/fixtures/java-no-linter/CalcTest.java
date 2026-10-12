public class CalcTest {
    public static void main(String[] args) {
        int got = Calc.add(2, 3);
        if (got != 5) {
            System.out.println("FAIL: add(2, 3) = " + got + ", expected 5");
            System.exit(1);
        }
        System.out.println("OK");
    }
}
