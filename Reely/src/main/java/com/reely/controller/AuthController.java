package com.reely.controller;

import com.reely.dto.MemberDto;
import com.reely.service.AuthService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private final AuthService authService;

    @Autowired
    public AuthController(AuthService authService) {
        this.authService = authService;
    }

    @GetMapping("/join")
    public ResponseEntity<String> join() {

        return new ResponseEntity<>("join", HttpStatus.OK);
    }

    @GetMapping("/login")
    public ResponseEntity<String> login() {
        return new ResponseEntity<>("login", HttpStatus.OK);
    }

    @GetMapping("/findAll")
    public ResponseEntity<List<MemberDto>> findAll() {
        List<MemberDto> list = authService.findAll();
        return new ResponseEntity<>(list, HttpStatus.OK);
    }
}
