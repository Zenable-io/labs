// Copyright (c) 2026 Zenable, Inc.
package lab.expenses;

public final class Refused extends RuntimeException {
    public Refused(String reason) {
        super(reason);
    }
}
