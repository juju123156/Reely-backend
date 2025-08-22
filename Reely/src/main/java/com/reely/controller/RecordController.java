package com.reely.controller;
import com.reely.security.SecurityUtil;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/record")
public class RecordController {
    @GetMapping
    public ResponseEntity<?> getRecords() {
        return ResponseEntity.ok("ok " + SecurityUtil.getCurrentMemberPk());
    }
}
