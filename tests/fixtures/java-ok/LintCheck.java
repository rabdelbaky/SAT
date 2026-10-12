// Stdlib "linter" for the java-* fixtures: no FIXME markers in *.java files.
// Run as a single-file source program: `java LintCheck.java`. Writes no files.
import java.io.IOException;
import java.nio.file.*;
import java.util.*;
import java.util.stream.*;

public class LintCheck {
    public static void main(String[] args) throws IOException {
        boolean failed = false;
        List<Path> files;
        try (Stream<Path> s = Files.list(Paths.get("."))) {
            files = s.filter(p -> p.toString().endsWith(".java"))
                     .filter(p -> !p.getFileName().toString().equals("LintCheck.java"))
                     .sorted().collect(Collectors.toList());
        }
        for (Path f : files) {
            List<String> lines = Files.readAllLines(f);
            for (int i = 0; i < lines.size(); i++) {
                if (lines.get(i).contains("FIXME")) {
                    System.out.println(f.getFileName() + ":" + (i + 1) + ": no-fixme");
                    failed = true;
                }
            }
        }
        System.exit(failed ? 1 : 0);
    }
}
